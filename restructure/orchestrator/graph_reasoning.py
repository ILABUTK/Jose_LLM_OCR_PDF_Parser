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
import svg_client

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
    status: str = "pending"   # pending → grounding → validating → comparing → expanding → illustrating → done
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
        self._root: Node | None = None

    # ---------------------------------------------------------------- helpers
    def _emit(self, node: Node | None = None, status: str | None = None) -> None:
        """Persist the whole graph after every change so a live viewer can poll it."""
        if node is not None and status is not None:
            node.status = status
        if self._root is not None:
            config.GRAPH_JSON.write_text(
                json.dumps(self._root.to_dict(), indent=2), encoding="utf-8")

    def _evidence_block(self, hits: list[dict]) -> str:
        lines = []
        for h in hits:
            lines.append(f"[{h['citekey']}] (sim={h.get('score',0)}): {h['text'][:400]}")
        return "\n".join(lines) if lines else "(no evidence retrieved)"

    def _ground(self, node: Node) -> None:
        self._emit(node, "grounding")
        query = f"{node.title}. {node.claim} " + " ".join(self.keywords)
        hits = self.corpus.search(query, k=6)
        node.evidence = hits
        node.citekeys = sorted({h["citekey"] for h in hits})
        self._emit()

    def _validate(self, node: Node) -> None:
        self._emit(node, "validating")
        res = complete_json(
            _VALIDATE_SYS,
            f"CLAIM:\n{node.claim}\n\nEVIDENCE:\n{self._evidence_block(node.evidence)}",
            temperature=0.0,
        )
        node.score = float(res["score"])
        node.validation = res["rationale"]
        self._emit()

    def _compare(self, node: Node, siblings: list[Node]) -> None:
        if not siblings:
            return
        self._emit(node, "comparing")
        sib = "\n".join(f"- {s.title}: {s.claim}" for s in siblings if s.id != node.id)
        node.comparison = complete(
            _COMPARE_SYS,
            f"CLAIM:\n{node.claim}\n\nSIBLING IDEAS:\n{sib}\n\n"
            f"COUNTER-EVIDENCE:\n{self._evidence_block(node.evidence[:3])}",
            temperature=0.2, max_tokens=800,
        )
        self._emit()

    def _illustrate(self, node: Node) -> None:
        self._emit(node, "illustrating")
        prompt = (
            f"Scientific figure illustrating: {node.title}. {node.claim}. "
            f"Clean schematic, labelled axes, publication quality, keywords: "
            f"{', '.join(self.keywords[:5])}."
        )
        node.figures = svg_client.generate_for_node(
            node.id, prompt, self._evidence_block(node.evidence), count=1)
        self._emit()

    def _expand(self, node: Node) -> list[dict]:
        ctx = (
            f"RESEARCH HYPOTHESIS: {self.hypothesis['hypothesis']}\n"
            f"KEYWORDS: {', '.join(self.keywords)}\n\n"
            f"PARENT IDEA: {node.title}\n{node.claim}\n\n"
            f"Propose exactly {config.GRAPH_BRANCHING} deeper sub-ideas."
        )
        res = complete_json(_EXPAND_SYS, ctx, temperature=0.5)
        return res["ideas"][: config.GRAPH_BRANCHING]

    # ---------------------------------------------------------------- traverse
    def _develop(self, node: Node, siblings: list[Node]) -> None:
        self._ground(node)
        self._validate(node)
        self._compare(node, siblings)
        print(f"  [graph] d{node.depth} score={node.score:.2f}  {node.title[:70]}")

        if node.depth >= config.GRAPH_DEPTH:
            self._emit(node, "done")
            return

        self._emit(node, "expanding")
        child_specs = self._expand(node)
        children: list[Node] = []
        for spec in child_specs:
            children.append(Node(
                id=f"n{next(_ids)}", title=spec["title"],
                claim=spec["claim"], depth=node.depth + 1, parent=node.id,
            ))
        node.children = children
        self._emit(node, "done")
        for child in children:
            self._develop(child, siblings=children)

    def _illustrate_top(self, root: Node) -> None:
        """Figures are placed only at the best-scoring nodes, up to
        PAPER_IMAGE_COUNT total for the whole paper (not one per node)."""
        nodes: list[Node] = []

        def collect(n: Node) -> None:
            if n.id != "root":
                nodes.append(n)
            for c in n.children:
                collect(c)

        collect(root)
        nodes.sort(key=lambda n: n.score, reverse=True)
        for node in nodes[: config.PAPER_IMAGE_COUNT]:
            print(f"  [graph] illustrate score={node.score:.2f}  {node.title[:70]}")
            self._illustrate(node)

    def build(self) -> Node:
        root = Node(
            id="root",
            title=self.hypothesis["title"],
            claim=self.hypothesis["hypothesis"],
            depth=0,
        )
        self._root = root
        self._ground(root)
        root.validation = "root hypothesis"
        root.score = 1.0
        root.status = "done"
        self._emit()
        seeds = self._seed_ideas(root)
        root.children = [
            Node(id=f"n{next(_ids)}", title=s["title"],
                 claim=s["claim"], depth=1, parent="root")
            for s in seeds
        ]
        self._emit()
        for child in root.children:
            self._develop(child, siblings=root.children)
        self._illustrate_top(root)
        return root

    def _seed_ideas(self, root: Node) -> list[dict]:
        """Top-level ideas derived from hypothesis + research questions."""
        rqs = self.hypothesis["research_questions"]
        ctx = (
            f"HYPOTHESIS: {root.claim}\n"
            f"RESEARCH QUESTIONS:\n" + "\n".join(f"- {q}" for q in rqs) + "\n\n"
            f"KEYWORDS: {', '.join(self.keywords)}\n\n"
            f"Propose {config.GRAPH_BRANCHING} top-level thematic ideas for the review."
        )
        return complete_json(_EXPAND_SYS, ctx, temperature=0.4)["ideas"][: config.GRAPH_BRANCHING]


def save_graph(root: Node) -> None:
    config.GRAPH_JSON.write_text(json.dumps(root.to_dict(), indent=2), encoding="utf-8")
    print(f"  [graph] saved → {config.GRAPH_JSON}")
