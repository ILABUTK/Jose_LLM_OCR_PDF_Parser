"""Graph-node based chain-of-thought reasoning engine.

This is the heart of the restructured pipeline and replaces the old linear
stage sequence (01→07). Reasoning is organised as a GRAPH, not a chain:

    ROOT (research hypothesis + keywords)
     ├── idea_1 ──┬── idea_1.1 ── …        (delve: GRAPH_DEPTH levels)
     │            └── idea_1.2 ── …
     ├── idea_2 ──…
     └── idea_3 ──…

At every node we:
  1. EXPAND   — spawn GRAPH_BRANCHING child sub-ideas that delve deeper.
  2. GROUND   — retrieve supporting evidence from the corpus (TF-IDF).
  3. VALIDATE — score how well the idea is supported [0,1]; prune weak nodes.
  4. COMPARE  — contrast the idea against sibling ideas / counter-evidence.
  5. ILLUSTRATE (optional) — when a node is well-developed, generate
     PAPER_IMAGE_COUNT vector SVG figures via the LLM, grounded in the node's
     retrieved corpus evidence.

Recursion stops at GRAPH_DEPTH. The resulting graph is serialised and later
flattened into paper sections.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import asdict, dataclass, field

import config
from corpus import Corpus
from llm_client import complete, complete_json

try:
    import svg_client
except Exception:  # figure generation optional at import time
    svg_client = None  # type: ignore

_ids = itertools.count(1)


@dataclass
class Node:
    id: str
    title: str
    claim: str
    depth: int
    parent: str | None = None
    evidence: list[dict] = field(default_factory=list)   # corpus hits
    citekeys: list[str] = field(default_factory=list)
    score: float = 0.0
    validation: str = ""
    comparison: str = ""
    figures: list[str] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["children"] = [c.to_dict() for c in self.children]
        return d


# ── Prompts ──────────────────────────────────────────────────────────────────
_EXPAND_SYS = (
    "You are a scientific reasoning engine building a review paper. Given a "
    "parent idea, propose distinct, non-overlapping SUB-IDEAS that delve one "
    "level deeper — each must be a concrete, verifiable sub-claim that advances "
    "the research hypothesis. Return JSON: "
    '{"ideas":[{"title":"...","claim":"..."}]}'
)

_VALIDATE_SYS = (
    "You are a rigorous reviewer. Given a CLAIM and retrieved EVIDENCE, decide "
    "how well the evidence supports the claim. Return JSON: "
    '{"score": <0..1 float>, "rationale":"<one paragraph>", '
    '"supported": <true|false>}'
)

_COMPARE_SYS = (
    "You are a scientific editor. Contrast the CLAIM against the SIBLING ideas "
    "and any counter-evidence. Identify agreements, tensions, and what makes "
    "this idea distinct. Return a concise paragraph."
)


class ReasoningGraph:
    def __init__(self, corpus: Corpus, hypothesis: dict, keywords: list[str]):
        self.corpus = corpus
        self.hypothesis = hypothesis
        self.keywords = keywords
        self.image_enabled = bool(svg_client) and svg_client.health() if svg_client else False
        if svg_client and not self.image_enabled:
            print("  [graph] SVG generator unavailable — figures disabled this run")

    # ---------------------------------------------------------------- helpers
    def _evidence_block(self, hits: list[dict]) -> str:
        lines = []
        for h in hits:
            lines.append(f"[{h['citekey']}] (sim={h.get('score',0)}): {h['text'][:400]}")
        return "\n".join(lines) if lines else "(no evidence retrieved)"

    def _ground(self, node: Node) -> None:
        query = f"{node.title}. {node.claim} " + " ".join(self.keywords)
        hits = self.corpus.search(query, k=6)
        node.evidence = hits
        node.citekeys = sorted({h["citekey"] for h in hits})

    def _validate(self, node: Node) -> None:
        try:
            res = complete_json(
                _VALIDATE_SYS,
                f"CLAIM:\n{node.claim}\n\nEVIDENCE:\n{self._evidence_block(node.evidence)}",
                temperature=0.0,
            )
            node.score = float(res.get("score", 0.0))
            node.validation = res.get("rationale", "")
        except Exception as e:
            node.score, node.validation = 0.0, f"(validation error: {e})"

    def _compare(self, node: Node, siblings: list[Node]) -> None:
        if not siblings:
            return
        sib = "\n".join(f"- {s.title}: {s.claim}" for s in siblings if s.id != node.id)
        try:
            node.comparison = complete(
                _COMPARE_SYS,
                f"CLAIM:\n{node.claim}\n\nSIBLING IDEAS:\n{sib}\n\n"
                f"COUNTER-EVIDENCE:\n{self._evidence_block(node.evidence[:3])}",
                temperature=0.2, max_tokens=800,
            )
        except Exception as e:
            node.comparison = f"(comparison error: {e})"

    def _illustrate(self, node: Node) -> None:
        if not self.image_enabled:
            return
        prompt = (
            f"Scientific figure illustrating: {node.title}. {node.claim}. "
            f"Clean schematic, labelled axes, publication quality, keywords: "
            f"{', '.join(self.keywords[:5])}."
        )
        node.figures = svg_client.generate_for_node(
            node.id, prompt, self._evidence_block(node.evidence))

    def _expand(self, node: Node) -> list[dict]:
        ctx = (
            f"RESEARCH HYPOTHESIS: {self.hypothesis.get('hypothesis','')}\n"
            f"KEYWORDS: {', '.join(self.keywords)}\n\n"
            f"PARENT IDEA: {node.title}\n{node.claim}\n\n"
            f"Propose exactly {config.GRAPH_BRANCHING} deeper sub-ideas."
        )
        try:
            res = complete_json(_EXPAND_SYS, ctx, temperature=0.5)
            return res.get("ideas", [])[: config.GRAPH_BRANCHING]
        except Exception as e:
            print(f"  [graph] expand failed at {node.id}: {e}")
            return []

    # ---------------------------------------------------------------- traverse
    def _develop(self, node: Node, siblings: list[Node]) -> None:
        self._ground(node)
        self._validate(node)
        self._compare(node, siblings)
        tag = "✓" if node.score >= config.GRAPH_MIN_SCORE else "✗"
        print(f"  [graph] d{node.depth} {tag} score={node.score:.2f}  {node.title[:70]}")

        if node.depth >= config.GRAPH_DEPTH:
            # Leaf of a well-supported branch → illustrate.
            if node.score >= config.GRAPH_MIN_SCORE:
                self._illustrate(node)
            return
        if node.score < config.GRAPH_MIN_SCORE:
            return  # prune weak branches — don't delve further

        child_specs = self._expand(node)
        children: list[Node] = []
        for spec in child_specs:
            children.append(Node(
                id=f"n{next(_ids)}", title=spec.get("title", "untitled"),
                claim=spec.get("claim", ""), depth=node.depth + 1, parent=node.id,
            ))
        node.children = children
        for child in children:
            self._develop(child, siblings=children)
        # Illustrate the developed parent node once its branch is explored.
        if node.depth >= 1:
            self._illustrate(node)

    def build(self) -> Node:
        root = Node(
            id="root",
            title=self.hypothesis.get("title", "Review"),
            claim=self.hypothesis.get("hypothesis", ""),
            depth=0,
        )
        self._ground(root)
        root.validation = "root hypothesis"
        root.score = 1.0
        seeds = self._seed_ideas(root)
        root.children = [
            Node(id=f"n{next(_ids)}", title=s.get("title", "untitled"),
                 claim=s.get("claim", ""), depth=1, parent="root")
            for s in seeds
        ]
        for child in root.children:
            self._develop(child, siblings=root.children)
        return root

    def _seed_ideas(self, root: Node) -> list[dict]:
        """Top-level ideas derived from hypothesis + research questions."""
        rqs = self.hypothesis.get("research_questions", [])
        ctx = (
            f"HYPOTHESIS: {root.claim}\n"
            f"RESEARCH QUESTIONS:\n" + "\n".join(f"- {q}" for q in rqs) + "\n\n"
            f"KEYWORDS: {', '.join(self.keywords)}\n\n"
            f"Propose {config.GRAPH_BRANCHING} top-level thematic ideas for the review."
        )
        try:
            return complete_json(_EXPAND_SYS, ctx, temperature=0.4).get("ideas", [])[: config.GRAPH_BRANCHING]
        except Exception:
            return [{"title": q[:60], "claim": q} for q in rqs][: config.GRAPH_BRANCHING]


def save_graph(root: Node) -> None:
    config.GRAPH_JSON.write_text(json.dumps(root.to_dict(), indent=2), encoding="utf-8")
    print(f"  [graph] saved → {config.GRAPH_JSON}")
