"""01 — Build two ontologies from a reference paper (Markdown).

Outputs:
    ontologies/structure_ontology.json  — section tree, evidence types, role per node
    ontologies/style_ontology.json      — how research questions are framed, voice,
                                          hedging, evidence frames, rhetorical moves

Approach (hybrid: deterministic + LLM):
  1. Deterministic parser tokenises headings and per-section content stats.
  2. Qwen3-Next thinking model annotates each node with semantic role and
     extracts style/rhetorical patterns globally.

Usage:
    python 01_extract_ontologies.py
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any

from config import (
    REFERENCE_MD,
    STRUCTURE_ONTOLOGY,
    STYLE_ONTOLOGY,
    PLANNER_MODEL,
    PLANNER_TEMPERATURE,
)
from ollama_client import chat_json

HEAD_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


# ── Deterministic structure pass ──────────────────────────────────────────────
def _infer_level(title: str, md_level: int) -> int:
    """Infer semantic section depth from the title numbering.
    Overrides the raw markdown heading depth (which is often uniform).

    '2.1.3. ...' → 3, '2.1. ...' → 2, '2. ...' → 1, unnumbered → 0
    Falls back to md_level if no numeric prefix detected.
    """
    import re as _re
    if _re.match(r'^\d+\.\d+\.\d+', title):
        return 3
    if _re.match(r'^\d+\.\d+', title):
        return 2
    if _re.match(r'^\d+\.', title):
        return 1
    # Unnumbered headings (Highlights, Funding, Acknowledgements, etc.) → 0
    return 0


def parse_sections(md: str) -> list[dict]:
    """Split markdown by ATX headings → flat list with text, level, body, stats."""
    matches = list(HEAD_RE.finditer(md))
    sections: list[dict] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        body = md[start:end].strip()
        sections.append({
            "id": f"sec_{i:03d}",
            "level": _infer_level(m.group(2).strip(), len(m.group(1))),
            "title": m.group(2).strip(),
            "body": body,
            "word_count": len(body.split()),
            "has_table": "|" in body and re.search(r"^\|", body, re.MULTILINE) is not None,
            "has_figure": bool(re.search(r"!\[.*?\]\(", body)),
            "citation_count": len(re.findall(r"\[\d+(?:[\-,\s]*\d+)*\]", body)),
        })
    return sections


def nest_sections(flat: list[dict]) -> list[dict]:
    """Turn flat list into tree by heading level."""
    root: list[dict] = []
    stack: list[dict] = []
    for s in flat:
        node = {**s, "children": []}
        while stack and stack[-1]["level"] >= node["level"]:
            stack.pop()
        if stack:
            stack[-1]["children"].append(node)
        else:
            root.append(node)
        stack.append(node)
    return root


# ── LLM annotation pass ───────────────────────────────────────────────────────
STRUCTURE_PROMPT = """You are analysing the structure of a scientific review paper.
For each section listed below, assign:
  - role:  one of {abstract, motivation, background, methods, results,
                   discussion, gaps, conclusion, frontmatter, backmatter, other}
  - purpose: 1-sentence description of what this section accomplishes
  - expected_evidence: list of evidence types it presents
                       (e.g. "experimental_data", "literature_synthesis",
                       "theoretical_model", "comparison_table",
                       "recommendation", "open_question")
  - research_questions_addressed: list of implicit research questions answered

Return STRICT JSON of the form:
{ "annotations": { "<section_id>": { "role": "...", "purpose": "...",
   "expected_evidence": [...], "research_questions_addressed": [...] }, ... } }

Sections:
"""


def annotate_structure(flat: list[dict], batch_size: int = 6) -> dict[str, dict]:
    """Annotate sections in small batches to avoid gateway timeouts."""
    all_ann: dict[str, dict] = {}
    for i in range(0, len(flat), batch_size):
        batch = flat[i : i + batch_size]
        payload = [
            {
                "id": s["id"],
                "level": s["level"],
                "title": s["title"],
                "word_count": s["word_count"],
                "citation_count": s["citation_count"],
                "preview": s["body"][:400],
            }
            for s in batch
        ]
        msg = [
            {"role": "system", "content":
                "You are a careful scientific text analyst. Output JSON only. "
                "Do not include reasoning or <think> tags."},
            {"role": "user", "content": STRUCTURE_PROMPT + json.dumps(payload, indent=2)},
        ]
        print(f"  [structure] batch {i // batch_size + 1}: "
              f"{len(batch)} sections …")
        out = chat_json(PLANNER_MODEL, msg,
                        temperature=PLANNER_TEMPERATURE, num_predict=2048)
        all_ann.update(out.get("annotations", {}))
    return all_ann


STYLE_PROMPT = """Analyse the rhetorical and stylistic conventions of this scientific
review paper. Return STRICT JSON with these top-level keys:

  "voice":               one of {first_person_plural, third_person, passive_dominant, mixed}
  "tense_dominant":      one of {past, present, mixed}
  "hedging_frequency":   one of {low, medium, high}
  "hedging_markers":     list of 5-15 representative phrases observed
                         (e.g. "may suggest", "is believed to", "appears to")
  "evidence_frames":     list of 4-8 patterns used to introduce evidence
                         (e.g. "Smith et al. [12] reported that ...",
                          "Experimental measurements indicate ...",
                          "According to ...")
  "research_question_patterns":
        list of 4-8 ways the paper poses or addresses research questions
        (e.g. "However, it remains unclear whether ...",
              "Few studies have systematically compared ...",
              "Open issues include ...")
  "rhetorical_moves":    ordered list of typical moves per section type
                         { "introduction": [...], "results": [...],
                           "gaps": [...], "conclusion": [...] }
  "citation_style":      one of {numeric_brackets, author_year, mixed}
  "average_sentence_length": integer (estimate)
  "transition_markers":  list of 6-12 transitions observed
                         (e.g. "Furthermore", "In contrast", "Notably")
  "domain_terminology_density": one of {low, medium, high}

Text sample (concatenated section openings):
"""


def annotate_style(flat: list[dict]) -> dict[str, Any]:
    # Smaller sample — server proxy times out on big prompts
    sample = "\n\n---\n\n".join(
        f"# {s['title']}\n{s['body'][:200]}"
        for s in flat
        if s["word_count"] > 30
    )[:6000]
    msg = [
        {"role": "system", "content":
            "You are a stylistic linguistics analyst. Output JSON only. "
            "Do not include reasoning or <think> tags."},
        {"role": "user", "content": STYLE_PROMPT + sample},
    ]
    return chat_json(PLANNER_MODEL, msg,
                     temperature=PLANNER_TEMPERATURE, num_predict=1536)


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    md = REFERENCE_MD.read_text(encoding="utf-8")
    flat = parse_sections(md)
    print(f"[structure] {len(flat)} sections parsed from {REFERENCE_MD.name}")

    # Extract style FIRST while bodies are still present
    print("[style] Extracting style ontology …")
    style = annotate_style(flat)
    style["source"] = str(REFERENCE_MD)
    STYLE_ONTOLOGY.write_text(json.dumps(style, indent=2), encoding="utf-8")
    print(f"[style] → {STYLE_ONTOLOGY}")

    print("[structure] Annotating with LLM …")
    annotations = annotate_structure(flat)

    # Merge annotations into nodes
    for s in flat:
        a = annotations.get(s["id"], {})
        s.update({
            "role": a.get("role", "other"),
            "purpose": a.get("purpose", ""),
            "expected_evidence": a.get("expected_evidence", []),
            "research_questions_addressed": a.get("research_questions_addressed", []),
        })
        # drop full body; keep a short preview in the ontology
        s["preview"] = s.pop("body")[:300]

    structure = {
        "source": str(REFERENCE_MD),
        "section_count": len(flat),
        "tree": nest_sections(flat),
    }
    STRUCTURE_ONTOLOGY.parent.mkdir(parents=True, exist_ok=True)
    STRUCTURE_ONTOLOGY.write_text(json.dumps(structure, indent=2), encoding="utf-8")
    print(f"[structure] → {STRUCTURE_ONTOLOGY}")


if __name__ == "__main__":
    main()
