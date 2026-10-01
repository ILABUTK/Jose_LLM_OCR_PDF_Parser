"""MCP server: SVG figure agent (ComfyUI replacement).

Exposes LLM-driven SVG figure generation as MCP tools. Instead of a GPU
diffusion service, figures are vector SVGs the LLM draws from a node's claim
and its retrieved corpus evidence.

Run standalone (stdio):   python -m mcp_servers.svg_server
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

import config
import svg_client
from mcp_servers import _state

mcp = FastMCP("figure")


@mcp.tool()
def svg_health() -> bool:
    """True if the SVG figure generator is available (always, no GPU needed)."""
    return svg_client.health()


@mcp.tool()
def generate_figure(node_id: str, prompt: str,
                    reference_citekeys: list[str] | None = None) -> list[str]:
    """Generate PAPER_IMAGE_COUNT SVG figures for a node.

    If `reference_citekeys` is given, the cited papers' figure captions are
    passed as grounding evidence so the drawing reflects real reported values.
    Returns the saved .svg paths.
    """
    evidence = None
    if reference_citekeys:
        c = _state.corpus()
        caps: list[str] = []
        for ck in reference_citekeys:
            for f in c.figures_for(ck):
                cap = f.get("caption") or f.get("path", "")
                caps.append(f"[{ck}] {cap}")
        evidence = "\n".join(caps) or None
    return svg_client.generate_for_node(node_id, prompt, evidence)


@mcp.tool()
def image_count() -> int:
    """The configured number of figures generated per node (PAPER_IMAGE_COUNT)."""
    return config.PAPER_IMAGE_COUNT


if __name__ == "__main__":
    mcp.run()
