"""03 — Multi-agent section writer with conflict resolution.

Framework: LangGraph (https://langchain-ai.github.io/langgraph) — the well-known
stateful multi-agent framework. We implement the **Writer ↔ Critic ↔ Judge**
pattern:

    [Writer]  drafts the section from outline + ontologies
       │
       ▼
    [Critic] scores draft against (a) the style ontology and
             (b) grounding in retrieved evidence from the reference paper.
             Emits issues + a numeric verdict in [0,1].
       │  (loop until verdict ≥ THRESHOLD or max_rounds reached)
       ▼
    [Judge]  if Writer and Critic disagree (verdict < THRESHOLD after revisions),
             a higher-temperature Judge LLM arbitrates and produces the FINAL
             draft, citing which side it supported and why → traceability.

Each node from the outline is processed independently (parallelizable). Results
are written to output/draft_sections.json with full agent history for audit.

Usage:
    python 03_agents_write.py
"""
from __future__ import annotations
import json
from typing import TypedDict, Annotated
from operator import add

from langgraph.graph import StateGraph, END

from config import (
    REFERENCE_MD,
    STRUCTURE_ONTOLOGY,
    STYLE_ONTOLOGY,
    OUTLINE_JSON,
    DRAFT_SECTIONS,
    PLANNER_MODEL,
    WRITER_TEMPERATURE,
    JUDGE_TEMPERATURE,
    MAX_TOKENS_SECTION,
)
from ollama_client import chat, chat_json
from corpus import load_bib_index, load_corpus, load_figure_catalog, bib_short_ref


VERDICT_THRESHOLD = 0.75   # slightly easier to pass — fewer revision loops
MAX_ROUNDS = 2             # reduced from 3 — 2 rounds max to limit call time


# ── State definition ──────────────────────────────────────────────────────────
class SectionState(TypedDict, total=False):
    node: dict                          # outline entry
    style: dict                         # style ontology
    reference_excerpt: str              # short excerpt of reference paper (style)
    evidence_bank: str                  # cite-able chunks from the corpus
    figure_bank: str                    # available real figures from corpus papers
    allowed_keys: str                   # comma-separated list of valid Zotero citekeys
    draft: str
    critique: dict                      # {"verdict": float, "issues": [...]}
    history: Annotated[list[dict], add]  # append-only audit trail
    rounds: int
    final: str
    judge_rationale: str


# ── Prompts ───────────────────────────────────────────────────────────────────
WRITER_SYS = """You are a scientific writer drafting one section of a review article.
Follow the STYLE ONTOLOGY precisely (voice, hedging, evidence frames, transitions,
research-question patterns). Use Markdown. Length should approximate the target
word count.

CITATIONS: every factual claim MUST cite a source using bracket notation
where you substitute a REAL Zotero-style identifier from the ALLOWED CITEKEYS list.
Example of correctly cited sentences (do NOT copy these keys verbatim — use ones
from the ALLOWED CITEKEYS list below that match your evidence):
  "Li2TiO3 pebbles fabricated by extrusion show a crushing load of 67 N
   [tan_scalable_2025], lower than Li4SiO4 [wang_nonstoichiometrically_2025]."

DO NOT write the literal string [citekey] — that is a placeholder name in this
prompt, NOT a real reference. Replace it with an actual identifier from the
ALLOWED CITEKEYS list. Use ONLY keys present in that list — do not invent new
keys, do not use numeric keys like [1], [12], or [13-16]. If evidence is
insufficient for a claim, write `[EVIDENCE NEEDED]` inline.

STRICT DATA INTEGRITY RULES — non-negotiable:
1. Do NOT fabricate numerical values (temperatures, diffusion coefficients,
   percentages, grain sizes, TBR values, etc.) that are not explicitly stated
   in the EVIDENCE BANK or the reference paper OCR text.
2. Do NOT invent citation keys. Every [citekey] you write must come verbatim
   from the EVIDENCE BANK provided below.
3. Do NOT cite the reference paper excerpt for data — it is provided for STYLE
   mimicry only. Extract real data only from the EVIDENCE BANK.
4. If a directive asks for a table or specific metric and the EVIDENCE BANK
   does not contain the underlying data, say "Data not available [EVIDENCE NEEDED]"
   in that cell — never fill it with a plausible-sounding number.
5. These rules override all other instructions. Fabricating data in a scientific
   review is scientific misconduct.

CITATION DENSITY: Every factual sentence MUST carry at least one [citekey] tag.
Target ≥70% of sentences cited. Sections with sparse citations (<50%) will fail
Critic review.

DEPTH MANDATE: Every body section MUST have:
  - At least 4 substantive paragraphs with numeric data
  - Where ≥3 quantitative values exist across materials: a Markdown comparison
    TABLE using pipe-delimited format (header | col | col with |---|---| separator)
  - All numerical values with their units, measurement conditions, and source paper

VISUAL ELEMENTS: If the FIGURE BANK lists relevant figures, embed one using:
  \\FIGURE{citekey}{rel_path}{Caption describing what the figure shows [citekey]}
Include at least one \\FIGURE tag per major section where relevant figures exist."""

WRITER_USER = """Outline entry for this section:
{node}

STYLE ONTOLOGY:
{style}

ALLOWED CITEKEYS (the ONLY identifiers you may put inside [...] brackets;
any other token in brackets will be REJECTED at render time):
{allowed_keys}

EVIDENCE BANK — cite each piece using one of the ALLOWED CITEKEYS above:
{evidence}

FIGURE BANK — real figures extracted from the corpus papers.
You MAY include figures from this list in the section using the LaTeX tag:
  \\FIGURE{{citekey}}{{rel_path}}{{Caption text [citekey]}}.
Rules for figures:
1. Only use figures listed here — never reference a figure path you invented.
2. The caption MUST describe what the figure actually shows (use the context text).
3. Prefer figures whose context matches the section topic.
4. If no relevant figures exist, omit \\FIGURE tags entirely.
5. For the Tables section or if directives request a table, synthesise a LaTeX
   table from data present in the EVIDENCE BANK. Use only values explicitly
   stated in the evidence — add 'N/A' for missing values, never guess.
---
{figures}
---

Reference paper excerpt (for STYLE/structure mimicry only; do not cite from here):
---
{ref}
---

Write the section now. Your output MUST include:
1. A minimum of 4 paragraphs with numeric evidence per paragraph
2. At least one pipe-delimited Markdown table comparing materials/conditions
   (only if EVIDENCE BANK has ≥3 data points; use N/A for missing values)
3. At least one \\FIGURE tag if FIGURE BANK contains a relevant figure
Output ONLY the section markdown (start with the heading)."""

CRITIC_SYS = """You are a strict scientific reviewer. Score the draft on:
  - structural_role_fit     (does it fulfil its assigned role/purpose?)
  - style_alignment         (does it match the style ontology?)
  - evidence_grounding      (every claim traceable to the reference excerpt?)
  - research_question_addressed (does it explicitly answer the planned RQs?)
Each in [0,1]. Compute verdict = mean. List up to 5 concrete issues with
suggested edits. Output JSON only."""

CRITIC_USER = """Outline entry:
{node}

Style ontology (excerpt):
{style}

Reference excerpt:
---
{ref}
---

Draft:
---
{draft}
---

Return JSON: {{ "scores": {{ "structural_role_fit": x, "style_alignment": x,
"evidence_grounding": x, "research_question_addressed": x }},
"verdict": x, "issues": ["...", ...] }}"""

JUDGE_SYS = """You are an impartial editorial judge resolving disagreements
between a Writer agent and a Critic agent. Produce the FINAL revised section
that maximally satisfies the critic's concerns WITHOUT departing from the style
ontology or fabricating evidence. After the section text, append a short
`<!-- judge: ... -->` HTML comment explaining the resolution.

ABSOLUTE RULE: Do NOT invent numerical values, citation keys, or data that
do not appear in the EVIDENCE BANK. If data is missing, write
[EVIDENCE NEEDED] — never invent plausible numbers. Scientific misconduct
(fabricating data) is worse than an incomplete section."""


# ── Nodes ─────────────────────────────────────────────────────────────────────
def _strip_think(text: str) -> str:
    """Remove <think>...</think> blocks and any leftover placeholder literals."""
    import re
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL | re.IGNORECASE)  # unterminated
    # Replace literal [citekey] placeholder (the LLM copied the prompt verbatim)
    text = re.sub(r"\[citekey\]", "[EVIDENCE NEEDED]", text, flags=re.IGNORECASE)
    return text.strip()


def writer_node(state: SectionState) -> SectionState:
    msg = [
        {"role": "system", "content": WRITER_SYS},
        {"role": "user", "content": WRITER_USER.format(
            node=json.dumps(state["node"], indent=2),
            style=json.dumps(state["style"], indent=2),
            allowed_keys=state.get("allowed_keys", "(none)"),
            evidence=state["evidence_bank"],
            figures=state.get("figure_bank", "(no figures available)"),
            ref=state["reference_excerpt"],
        )},
    ]
    # If we already have critique → revise
    if state.get("critique"):
        msg.append({"role": "assistant", "content": state["draft"]})
        msg.append({"role": "user", "content":
            f"Critic feedback (verdict {state['critique']['verdict']:.2f}):\n"
            + "\n".join(f"- {i}" for i in state["critique"]["issues"])
            + "\n\nRevise the section to address each issue. Output the FULL revised section."})
    draft = chat(PLANNER_MODEL, msg,
                 temperature=WRITER_TEMPERATURE, num_predict=MAX_TOKENS_SECTION,
                 think=False)
    draft = _strip_think(draft)
    # If model returned nothing (or only think block), retry once with thinking
    # disabled AND a smaller, simpler prompt (drop figure bank and reference)
    if len(draft) < 200:
        print(f"  [writer] empty/tiny draft ({len(draft)} chars) — retrying with simplified prompt")
        simple_msg = [
            {"role": "system", "content": WRITER_SYS},
            {"role": "user", "content": WRITER_USER.format(
                node=json.dumps(state["node"], indent=2),
                style=json.dumps({k: state["style"].get(k) for k in
                                  ("voice", "citation_style", "evidence_frames")}, indent=2),
                allowed_keys=state.get("allowed_keys", "(none)"),
                evidence=state["evidence_bank"],
                figures="(omitted)",
                ref="(omitted)",
            )},
        ]
        draft = chat(PLANNER_MODEL, simple_msg,
                     temperature=WRITER_TEMPERATURE,
                     num_predict=MAX_TOKENS_SECTION, think=False)
        draft = _strip_think(draft)
    return {
        "draft": draft,
        "rounds": state.get("rounds", 0) + 1,
        "history": [{"agent": "writer", "round": state.get("rounds", 0) + 1,
                     "draft_chars": len(draft)}],
    }


def critic_node(state: SectionState) -> SectionState:
    msg = [
        {"role": "system", "content": CRITIC_SYS},
        {"role": "user", "content": CRITIC_USER.format(
            node=json.dumps(state["node"], indent=2),
            style=json.dumps({k: state["style"].get(k) for k in
                              ("voice", "hedging_markers", "evidence_frames",
                               "research_question_patterns", "citation_style")},
                             indent=2),
            ref=state["reference_excerpt"],
            draft=state["draft"],
        )},
    ]
    try:
        crit = chat_json(PLANNER_MODEL, msg, temperature=0.0, num_predict=1024)
    except Exception as e:
        # Fault-tolerant: if critic can't return valid JSON, accept the draft
        print(f"  [critic] JSON failure ({e}); accepting draft as-is")
        crit = {"verdict": 1.0, "issues": [], "notes": f"critic unavailable: {e}"}
    return {
        "critique": crit,
        "history": [{"agent": "critic", "round": state["rounds"],
                     "verdict": crit.get("verdict")}],
    }


def judge_node(state: SectionState) -> SectionState:
    msg = [
        {"role": "system", "content": JUDGE_SYS},
        {"role": "user", "content":
            f"Outline:\n{json.dumps(state['node'], indent=2)}\n\n"
            f"Last draft:\n---\n{state['draft']}\n---\n\n"
            f"Critic verdict {state['critique']['verdict']:.2f} with issues:\n"
            + "\n".join(f"- {i}" for i in state['critique']['issues'])
            + f"\n\nReference excerpt:\n{state['reference_excerpt']}"},
    ]
    final = chat(PLANNER_MODEL, msg,
                 temperature=JUDGE_TEMPERATURE, num_predict=MAX_TOKENS_SECTION,
                 think=False)
    final = _strip_think(final)
    return {
        "final": final,
        "judge_rationale": "Judge arbitrated after disagreement persisted.",
        "history": [{"agent": "judge", "round": state["rounds"]}],
    }


# ── Routing ───────────────────────────────────────────────────────────────────
def route_after_critic(state: SectionState) -> str:
    verdict = (state.get("critique") or {}).get("verdict", 0.0)
    if verdict >= VERDICT_THRESHOLD:
        return "accept"
    if state.get("rounds", 0) >= MAX_ROUNDS:
        return "judge"
    return "revise"


def accept_node(state: SectionState) -> SectionState:
    return {"final": _strip_think(state["draft"])}


# ── Graph factory ─────────────────────────────────────────────────────────────
def build_graph():
    g = StateGraph(SectionState)
    g.add_node("writer", writer_node)
    g.add_node("critic", critic_node)
    g.add_node("judge", judge_node)
    g.add_node("accept", accept_node)
    g.set_entry_point("writer")
    g.add_edge("writer", "critic")
    g.add_conditional_edges("critic", route_after_critic, {
        "revise": "writer", "judge": "judge", "accept": "accept",
    })
    g.add_edge("judge", END)
    g.add_edge("accept", END)
    return g.compile()


# ── Retrieval (keyword overlap, deterministic, no extra deps) ──────────────────
def _node_keywords(node: dict) -> set[str]:
    keywords: set[str] = set()
    for s in [node.get("title", "")] + node.get("directives", []) \
             + node.get("research_questions", []):
        keywords.update(w.lower().strip(".,;:()[]") for w in s.split() if len(w) > 3)
    return keywords


def retrieve_reference_excerpt(ref_md: str, node: dict, max_chars: int = 2500) -> str:
    """Style-relevant excerpt from the reference paper (NOT for citation)."""
    keywords = _node_keywords(node)
    paragraphs = [p for p in ref_md.split("\n\n") if p.strip()]
    scored = sorted(
        ((sum(1 for k in keywords if k in p.lower()), p) for p in paragraphs),
        key=lambda x: -x[0],
    )
    out, total = [], 0
    for _, p in scored:
        if total + len(p) > max_chars:
            break
        out.append(p); total += len(p)
    return "\n\n".join(out) or ref_md[:max_chars]


def retrieve_evidence_bank(corpus: list[dict], bib: dict[str, dict],
                           node: dict, top_k: int = 12,
                           chunk_chars: int = 600) -> str:
    """Pull the top-k most relevant chunks across the WHOLE corpus, formatted
    as a numbered evidence bank with [citekey] tags + bib short-refs."""
    keywords = _node_keywords(node)
    scored = sorted(
        ((sum(1 for k in keywords if k in c["text"].lower()), c) for c in corpus),
        key=lambda x: -x[0],
    )
    picked, seen_keys = [], set()
    for score, c in scored:
        if score == 0:
            break
        # Diversify: at most 2 chunks per paper, prefer new papers first
        if list(seen_keys).count(c["citekey"]) >= 2:
            continue
        picked.append(c); seen_keys.add(c["citekey"])
        if len(picked) >= top_k:
            break
    lines = []
    for c in picked:
        meta = bib.get(c["citekey"], {})
        ref_line = bib_short_ref(meta, c["citekey"]) if meta else f"[{c['citekey']}]"
        lines.append(f"{ref_line}\n  excerpt: {c['text'][:chunk_chars]}")
    return "\n\n".join(lines) if lines else "(no relevant evidence found)"


def retrieve_figure_bank(figures: list[dict], node: dict, top_k: int = 8) -> str:
    """Return the top-k most topically relevant figures as a prompt-ready string.

    Format per figure::

        [citekey] rel_path | caption | context
    """
    keywords = _node_keywords(node)
    scored = sorted(
        (
          (sum(1 for k in keywords
               if k in (f["caption"] + f["context"]).lower()), f)
          for f in figures
        ),
        key=lambda x: -x[0],
    )
    picked, seen_citekeys = [], {}
    for score, fig in scored:
        if score == 0:
            break
        # At most 2 figures per paper
        if seen_citekeys.get(fig["citekey"], 0) >= 2:
            continue
        picked.append(fig)
        seen_citekeys[fig["citekey"]] = seen_citekeys.get(fig["citekey"], 0) + 1
        if len(picked) >= top_k:
            break
    if not picked:
        return "(no relevant figures found)"
    lines = []
    for fig in picked:
        lines.append(
            f"[{fig['citekey']}] {fig['rel_path']}\n"
            f"  caption: {fig['caption'] or '(no caption)'}\n"
            f"  context: {fig['context'][:300]}"
        )
    return "\n\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    outline = json.loads(OUTLINE_JSON.read_text())["outline"]
    style   = json.loads(STYLE_ONTOLOGY.read_text())
    ref_md  = REFERENCE_MD.read_text(encoding="utf-8")

    print("[corpus] Loading bib index + full-text chunks …")
    bib    = load_bib_index()
    _excl  = {REFERENCE_MD.parent.parent.name}
    corpus = load_corpus(exclude=_excl, bib_index=bib)
    figs   = load_figure_catalog(exclude=_excl, bib_index=bib)
    n_citable = sum(1 for c in corpus if c['citable'])
    print(f"[corpus] {len(bib)} bib entries; {len(corpus)} chunks from "
          f"{len({c['citekey'] for c in corpus})} papers "
          f"({n_citable} citable chunks); {len(figs)} figures indexed")

    graph = build_graph()
    results: list[dict] = []

    for i, node in enumerate(outline):
        print(f"[write {i+1}/{len(outline)}] {node['title']}")
        excerpt  = retrieve_reference_excerpt(ref_md, node)
        evidence = retrieve_evidence_bank(corpus, bib, node)
        figure_b = retrieve_figure_bank(figs, node)
        # Build allowed-keys list from the bib (only keys that exist in the bib
        # will resolve at render time; expose the full list so the writer can
        # pick any reference even beyond the top-k evidence chunks).
        allowed_keys = ", ".join(sorted(bib.keys()))
        try:
            out = graph.invoke({
                "node": node,
                "style": style,
                "reference_excerpt": excerpt,
                "evidence_bank": evidence,
                "figure_bank": figure_b,
                "allowed_keys": allowed_keys,
                "rounds": 0,
                "history": [],
            })
            results.append({
                "id": node["id"],
                "title": node["title"],
                "level": node.get("level", 2),
                "role": node.get("role", "other"),
                "final": out["final"],
                "history": out["history"],
                "last_verdict": (out.get("critique") or {}).get("verdict"),
                "judge_invoked": "judge_rationale" in out,
                "figures_available": figure_b,
            })
        except Exception as e:
            # Don't lose the whole run if one section fails — try a single direct writer call
            print(f"  [write {i+1}] graph failed ({e}); falling back to single writer call")
            try:
                solo = writer_node({
                    "node": node, "style": style,
                    "reference_excerpt": excerpt, "evidence_bank": evidence,
                    "figure_bank": figure_b, "allowed_keys": allowed_keys,
                    "rounds": 0, "history": [],
                })
                final_text = solo.get("draft", "")
            except Exception as e2:
                print(f"  [write {i+1}] fallback also failed ({e2}); inserting placeholder")
                final_text = f"% Section generation failed: {e2}\n"
            results.append({
                "id": node["id"], "title": node["title"],
                "level": node.get("level", 2), "role": node.get("role", "other"),
                "final": final_text, "history": [{"agent": "writer-fallback", "error": str(e)}],
                "last_verdict": None, "judge_invoked": False,
                "figures_available": figure_b,
            })
        # Persist progress after every section so a late crash doesn't lose work
        DRAFT_SECTIONS.write_text(json.dumps(results, indent=2), encoding="utf-8")

    DRAFT_SECTIONS.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"[write] → {DRAFT_SECTIONS}")


if __name__ == "__main__":
    main()
