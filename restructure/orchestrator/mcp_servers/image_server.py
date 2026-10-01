"""MCP server: image / ComfyUI agent.

Exposes figure generation (PAPER_IMAGE_COUNT images per node, optionally using a
cited paper's own figures as img2img references) as MCP tools.

Run standalone (stdio):   python -m mcp_servers.image_server
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

import comfy_client
import config
from mcp_servers import _state

mcp = FastMCP("image")


@mcp.tool()
def comfy_health() -> bool:
    """True if the ComfyUI service is reachable."""
    return comfy_client.health()


@mcp.tool()
def generate_figure(node_id: str, prompt: str, reference_citekeys: list[str] | None = None) -> list[str]:
    """Generate PAPER_IMAGE_COUNT figures for a node.

    If `reference_citekeys` is given, the cited papers' own embedded figures are
    used as img2img references. Returns the saved image paths.
    """
    refs: list[str] = []
    if reference_citekeys:
        c = _state.corpus()
        for ck in reference_citekeys:
            refs.extend(f["path"] for f in c.figures_for(ck))
    return comfy_client.generate_for_node(node_id, prompt, refs or None)


@mcp.tool()
def image_count() -> int:
    """The configured number of images generated per node (PAPER_IMAGE_COUNT)."""
    return config.PAPER_IMAGE_COUNT


if __name__ == "__main__":
    mcp.run()
