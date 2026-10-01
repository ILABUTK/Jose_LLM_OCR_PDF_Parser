"""Pipeline orchestrator — the restructured replacement for run_pipeline.sh.

Linear stages 01→07 are replaced by a single graph-of-thought traversal:

    load inputs → build reasoning graph (GRAPH_DEPTH) → illustrate (ComfyUI)
                → draft grounded sections → assemble paper.md

Run:
    python pipeline.py                 # full run
    python pipeline.py --graph-only    # stop after the reasoning graph
    python pipeline.py --depth 4       # override GRAPH_DEPTH
"""
from __future__ import annotations

import argparse
import json

import config
from corpus import load_corpus
from graph_reasoning import Node, ReasoningGraph, save_graph
from llm_client import complete
from style import style_summary


def _load_hypothesis() -> dict:
    if not config.HYPOTHESIS_JSON.exists():
        raise SystemExit(f"Missing {config.HYPOTHESIS_JSON} — provide a research hypothesis.")
    return json.loads(config.HYPOTHESIS_JSON.read_text(encoding="utf-8"))


def _load_keywords() -> list[str]:
    if not config.KEYWORDS_JSON.exists():
        return []
    data = json.loads(config.KEYWORDS_JSON.read_text(encoding="utf-8"))
    return data.get("keywords", data) if isinstance(data, dict) else data


_WRITER_SYS = (
    "You are a scientific writer drafting one section of a review article. "
    "Follow the STYLE GUIDE precisely. Every factual claim MUST cite a source "
    "using [citekey], using ONLY keys from the ALLOWED CITEKEYS list. Never "
    "invent citekeys or numbers absent from the evidence. Output Markdown. "
    "Integrate the comparison and validation reasoning provided."
)


def _draft_node(node: Node, corpus, style: str) -> str:
    hits = node.evidence or corpus.search(f"{node.title}. {node.claim}", k=8)
    allowed = sorted({h["citekey"] for h in hits})
    evidence = "\n".join(f"[{h['citekey']}] {h['text'][:500]}" for h in hits)
    user = (
        f"STYLE GUIDE:\n{style}\n\n"
        f"SECTION TITLE: {node.title}\n"
        f"CENTRAL CLAIM: {node.claim}\n\n"
        f"VALIDATION REASONING: {node.validation}\n"
        f"COMPARISON TO SIBLINGS: {node.comparison}\n\n"
        f"ALLOWED CITEKEYS: {', '.join(allowed) or '(none)'}\n\n"
        f"EVIDENCE BANK:\n{evidence}\n\n"
        "Write the section now (2-4 paragraphs)."
    )
    try:
        return complete(_WRITER_SYS, user, temperature=0.4, max_tokens=3000)
    except Exception as e:
        return f"_(draft error: {e})_"


def _assemble(root: Node, corpus, style: str) -> None:
    """Flatten the graph depth-first into Markdown sections and figures."""
    sections: list[dict] = []
    lines: list[str] = [f"# {root.title}\n", f"*{root.claim}*\n"]

    def walk(node: Node, level: int) -> None:
        if node.id != "root" and node.score >= config.GRAPH_MIN_SCORE:
            heading = "#" * min(level + 1, 5)
            lines.append(f"\n{heading} {node.title}\n")
            body = _draft_node(node, corpus, style)
            lines.append(body + "\n")
            for fig in node.figures:
                rel = config.FIGURES_DIR.name + "/" + fig.split("/")[-1]
                lines.append(f"\n![{node.title}]({rel})\n")
            sections.append({
                "id": node.id, "title": node.title, "depth": node.depth,
                "score": node.score, "citekeys": node.citekeys,
                "figures": node.figures, "body": body,
            })
            print(f"  [draft] {node.id} {node.title[:60]}")
        for child in node.children:
            walk(child, level + 1)

    walk(root, 0)

    # References section
    used = sorted({ck for s in sections for ck in s["citekeys"]})
    if used:
        lines.append("\n## References\n")
        for ck in used:
            lines.append(f"- {corpus.short_ref(ck)}")

    config.DRAFT_JSON.write_text(json.dumps(sections, indent=2), encoding="utf-8")
    config.PAPER_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"  [assemble] {len(sections)} sections → {config.PAPER_MD}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph-only", action="store_true")
    ap.add_argument("--depth", type=int, default=None)
    args = ap.parse_args()
    if args.depth is not None:
        config.GRAPH_DEPTH = args.depth

    print("=== restructured paper pipeline ===")
    print(f"  LLM: {config.LLM_MODEL} @ {config.LLM_BASE_URL}")
    print(f"  GRAPH_DEPTH={config.GRAPH_DEPTH}  PAPER_IMAGE_COUNT={config.PAPER_IMAGE_COUNT}")

    hypothesis = _load_hypothesis()
    keywords = _load_keywords()
    corpus = load_corpus()
    style = style_summary()

    print("--- building reasoning graph ---")
    graph = ReasoningGraph(corpus, hypothesis, keywords)
    root = graph.build()
    save_graph(root)

    if args.graph_only:
        print("graph-only: stopping before drafting.")
        return

    print("--- drafting + assembling paper ---")
    _assemble(root, corpus, style)
    print("=== done ===")
    print(f"  graph : {config.GRAPH_JSON}")
    print(f"  draft : {config.DRAFT_JSON}")
    print(f"  paper : {config.PAPER_MD}")


if __name__ == "__main__":
    main()
