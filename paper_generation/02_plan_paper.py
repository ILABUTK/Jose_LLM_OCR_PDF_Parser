"""02 — Generate an outline for the NEW paper that mirrors the reference ontology.

Batches sections 4 at a time so individual API calls stay under the nginx
gateway timeout (~120 s).  Uses the PLANNER_MODEL (qwen3:32b by default).

Output: output/outline.json
    { "topic": "...", "outline": [
        { "id": "sec_000", "title": "...", "level": 2, "role": "...",
          "directives": [...], "expected_evidence": [...],
          "research_questions": [...], "target_word_count": int }, ... ] }

Usage:
    python 02_plan_paper.py --topic "Lithium orthosilicate as tritium breeder: \
        a comparative review with Li2TiO3 and Li2ZrO3"
"""
from __future__ import annotations
import argparse
import json

from config import (
    STRUCTURE_ONTOLOGY,
    STYLE_ONTOLOGY,
    OUTLINE_JSON,
    PLANNER_MODEL,
    PLANNER_TEMPERATURE,
    PAPER_TOPIC,
)
from ollama_client import chat_json

# Sections per API call — keep small so generation stays under 90 s
BATCH_SIZE = 4

BATCH_PROMPT = """You are planning sections of a new Elsevier-style scientific review paper.

Topic: {topic}

Style register to match:
{style}

For each section stub below produce an outline entry with ALL of these keys:
  id               (copy exactly)
  title            (new title appropriate for the topic, parallel to original role)
  level            (copy)
  role             (copy)
  directives       (list of 3-5 imperative bullet strings: what the writer must cover)
  expected_evidence (list of evidence types needed, e.g. "XRD data", "TEM micrographs")
  research_questions (list of 1-3 precise questions this section answers)
  target_word_count  (integer; ~300-600 for leaf sections, ~100 for boilerplate)

Section stubs to plan:
{stubs}

Return STRICT JSON: {{ "outline": [ {{ ... }}, ... ] }}
Only include the {n} sections listed above — no extras.
"""


def flatten(nodes: list, out: list) -> list:
    for n in nodes:
        out.append({k: n.get(k) for k in
                    ("id", "level", "title", "role", "purpose",
                     "expected_evidence", "research_questions_addressed")})
        flatten(n.get("children", []), out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default=PAPER_TOPIC,
                    help="Topic of the new paper (default: PAPER_TOPIC from config)")
    args = ap.parse_args()

    structure = json.loads(STRUCTURE_ONTOLOGY.read_text())
    style     = json.loads(STYLE_ONTOLOGY.read_text())

    flat = flatten(structure["tree"], [])
    print(f"[plan] {len(flat)} sections → batches of {BATCH_SIZE}")

    style_short = {k: style.get(k) for k in
                   ("voice", "hedging_phrases", "evidence_framing", "paragraph_structure")}

    outline_entries: list[dict] = []
    for i in range(0, len(flat), BATCH_SIZE):
        batch = flat[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(flat) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"[plan] batch {batch_num}/{total_batches}: "
              f"{[s['id'] for s in batch]}")

        msg = [
            {"role": "system",
             "content": "You are a senior scientific editor. Output JSON only. "
                        "Be concise in your reasoning — produce the JSON answer directly."},
            {"role": "user",
             "content": BATCH_PROMPT.format(
                 topic=args.topic,
                 style=json.dumps(style_short, indent=2),
                 stubs=json.dumps(batch, indent=2),
                 n=len(batch),
             )},
        ]
        result = chat_json(PLANNER_MODEL, msg,
                           temperature=PLANNER_TEMPERATURE, num_predict=4096)
        entries = result.get("outline", [])
        if not entries:
            # fallback: maybe the model returned a list directly
            entries = result if isinstance(result, list) else []
        outline_entries.extend(entries)
        print(f"  → {len(entries)} entries received (total so far: {len(outline_entries)})")

    OUTLINE_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTLINE_JSON.write_text(
        json.dumps({"topic": args.topic, "outline": outline_entries}, indent=2),
        encoding="utf-8",
    )
    print(f"[plan] done — {len(outline_entries)} sections → {OUTLINE_JSON}")


if __name__ == "__main__":
    main()
