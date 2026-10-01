"""MCP server: writing agent.

Turns a developed reasoning node (claim + evidence + figures) into grounded
prose that follows the author's style reference, and critiques drafts.

Run standalone (stdio):   python -m mcp_servers.writing_server
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from llm_client import complete, complete_json
from mcp_servers import _state
from style import style_summary

mcp = FastMCP("writing")

_WRITER_SYS = (
    "You are a scientific writer drafting one section of a review article. "
    "Follow the STYLE GUIDE precisely. Every factual claim MUST cite a source "
    "using [citekey] with keys taken ONLY from the ALLOWED CITEKEYS list. Never "
    "invent citekeys or numeric data not present in the evidence. Use Markdown."
)
_CRITIC_SYS = (
    "You are a strict reviewer. Score a draft section for grounding, citation "
    'density, and style adherence. Return JSON: {"verdict":<0..1>,"issues":[...]}'
)


@mcp.tool()
def draft_section(title: str, claim: str, k: int = 8) -> str:
    """Draft a grounded Markdown section for an idea, citing corpus evidence."""
    c = _state.corpus()
    hits = c.search(f"{title}. {claim}", k=k)
    allowed = sorted({h["citekey"] for h in hits})
    evidence = "\n".join(f"[{h['citekey']}] {h['text'][:500]}" for h in hits)
    user = (
        f"STYLE GUIDE:\n{style_summary()}\n\n"
        f"SECTION TITLE: {title}\n"
        f"CENTRAL CLAIM: {claim}\n\n"
        f"ALLOWED CITEKEYS: {', '.join(allowed) or '(none)'}\n\n"
        f"EVIDENCE BANK:\n{evidence}\n\n"
        "Write the section now."
    )
    return complete(_WRITER_SYS, user, temperature=0.4, max_tokens=3000)


@mcp.tool()
def critique_section(draft: str) -> dict:
    """Score a drafted section and list concrete issues."""
    return complete_json(_CRITIC_SYS, f"DRAFT:\n{draft}", temperature=0.0)


if __name__ == "__main__":
    mcp.run()
