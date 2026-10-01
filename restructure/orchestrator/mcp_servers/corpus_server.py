"""MCP server: corpus / evidence agent.

Exposes the mounted PDF+bib corpus as MCP tools so any MCP-capable agent can
retrieve grounded evidence without knowing about the underlying storage.

Run standalone (stdio):   python -m mcp_servers.corpus_server
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_servers import _state

mcp = FastMCP("corpus")


@mcp.tool()
def list_papers() -> list[dict]:
    """List every paper in the corpus with its citekey and short reference."""
    c = _state.corpus()
    keys = sorted({ch["citekey"] for ch in c.chunks})
    return [{"citekey": k, "reference": c.short_ref(k)} for k in keys]


@mcp.tool()
def search_evidence(query: str, k: int = 6) -> list[dict]:
    """Retrieve the top-k most relevant evidence chunks for a query.

    Returns a list of {citekey, chunk_id, score, text}.
    """
    return _state.corpus().search(query, k=k)


@mcp.tool()
def get_figures(citekey: str) -> list[dict]:
    """Return the figures embedded in a given paper (by citekey)."""
    return _state.corpus().figures_for(citekey)


@mcp.tool()
def short_ref(citekey: str) -> str:
    """One-line human-readable reference for a citekey."""
    return _state.corpus().short_ref(citekey)


if __name__ == "__main__":
    mcp.run()
