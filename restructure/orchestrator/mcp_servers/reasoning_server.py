"""MCP server: graph-reasoning agent.

Exposes the primitive operations of the graph chain-of-thought (expand /
validate / compare) as MCP tools, plus a `build_graph` tool that runs the full
GRAPH_DEPTH traversal in one call.

Run standalone (stdio):   python -m mcp_servers.reasoning_server
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

import config
from graph_reasoning import ReasoningGraph, Node, save_graph
from llm_client import complete, complete_json
from mcp_servers import _state

mcp = FastMCP("reasoning")

_EXPAND_SYS = (
    "You are a scientific reasoning engine. Given a parent idea, propose "
    "distinct deeper sub-ideas, each a concrete verifiable sub-claim. "
    'Return JSON: {"ideas":[{"title":"...","claim":"..."}]}'
)
_VALIDATE_SYS = (
    "You are a rigorous reviewer. Score how well EVIDENCE supports a CLAIM. "
    'Return JSON: {"score":<0..1>,"rationale":"...","supported":<bool>}'
)


@mcp.tool()
def expand_idea(title: str, claim: str, branching: int | None = None) -> list[dict]:
    """Spawn deeper sub-ideas from a parent idea (one level of the graph)."""
    b = branching or config.GRAPH_BRANCHING
    ctx = f"PARENT IDEA: {title}\n{claim}\n\nPropose exactly {b} deeper sub-ideas."
    return complete_json(_EXPAND_SYS, ctx, temperature=0.5).get("ideas", [])[:b]


@mcp.tool()
def validate_claim(claim: str, k: int = 6) -> dict:
    """Ground a claim in the corpus and score its evidential support [0,1]."""
    hits = _state.corpus().search(claim, k=k)
    evidence = "\n".join(f"[{h['citekey']}] {h['text'][:400]}" for h in hits)
    res = complete_json(_VALIDATE_SYS, f"CLAIM:\n{claim}\n\nEVIDENCE:\n{evidence}", temperature=0.0)
    res["citekeys"] = sorted({h["citekey"] for h in hits})
    return res


@mcp.tool()
def build_graph(depth: int | None = None) -> dict:
    """Run the full graph-of-thought traversal to GRAPH_DEPTH and persist it.

    Returns a summary {num_nodes, max_depth, path}.
    """
    if depth is not None:
        config.GRAPH_DEPTH = depth
    g = ReasoningGraph(_state.corpus(), _state.hypothesis(), _state.keywords())
    root = g.build()
    save_graph(root)

    def _count(n: Node) -> int:
        return 1 + sum(_count(c) for c in n.children)

    return {"num_nodes": _count(root), "max_depth": config.GRAPH_DEPTH,
            "path": str(config.GRAPH_JSON)}


if __name__ == "__main__":
    mcp.run()
