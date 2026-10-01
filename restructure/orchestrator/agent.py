"""MCP orchestrator agent.

This is the "LLM agents" entrypoint required by the spec: it launches the four
MCP servers (corpus, reasoning, image, writing) as stdio subprocesses, exposes
their tools to the external vLLM model, and runs a tool-calling loop so the
model orchestrates the whole paper build itself.

The deterministic engine lives in `pipeline.py`; this file is the agentic
counterpart that drives the SAME MCP tools via the LLM. Choose either entrypoint
in docker-compose (PIPELINE_MODE=agent|pipeline).

Run:
    python agent.py
"""
from __future__ import annotations

import asyncio
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import config
from llm_client import chat

SERVERS = {
    "corpus": ["python", "-m", "mcp_servers.corpus_server"],
    "reasoning": ["python", "-m", "mcp_servers.reasoning_server"],
    "figure": ["python", "-m", "mcp_servers.svg_server"],
    "writing": ["python", "-m", "mcp_servers.writing_server"],
}

SYSTEM = f"""You are the orchestrator of an automated scientific-review pipeline.
You have MCP tools from four agents: corpus (evidence), reasoning (graph of
thought), figure (LLM-drawn SVG figures), writing (grounded prose).

Goal: build a grounded review paper from the mounted corpus.
Procedure:
  1. Call reasoning.build_graph with depth={config.GRAPH_DEPTH} to produce the
     graph-of-thought (it validates and illustrates nodes automatically).
  2. Inspect the corpus with corpus.list_papers if useful.
  3. For the strongest nodes, call writing.draft_section to produce prose.
Keep calls purposeful. When finished, reply with a short completion summary.
"""


def _to_openai_tool(server: str, tool) -> dict:
    return {
        "type": "function",
        "function": {
            "name": f"{server}__{tool.name}",
            "description": (tool.description or "")[:1024],
            "parameters": tool.inputSchema or {"type": "object", "properties": {}},
        },
    }


async def run() -> None:
    import contextlib

    async with contextlib.AsyncExitStack() as stack:
        sessions: dict[str, ClientSession] = {}
        tools: list[dict] = []
        tool_owner: dict[str, tuple[str, str]] = {}

        for name, cmd in SERVERS.items():
            params = StdioServerParameters(command=cmd[0], args=cmd[1:])
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            sessions[name] = session
            listed = await session.list_tools()
            for t in listed.tools:
                tools.append(_to_openai_tool(name, t))
                tool_owner[f"{name}__{t.name}"] = (name, t.name)
            print(f"  [agent] connected MCP server '{name}' ({len(listed.tools)} tools)")

        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Build the review paper now."},
        ]

        for step in range(24):
            msg = chat(messages, tools=tools, tool_choice="auto")
            messages.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                print("  [agent] done:", (msg.get("content") or "")[:400])
                break
            for call in calls:
                fn = call["function"]["name"]
                args = json.loads(call["function"].get("arguments") or "{}")
                server, tool_name = tool_owner[fn]
                print(f"  [agent] → {fn}({json.dumps(args)[:120]})")
                result = await sessions[server].call_tool(tool_name, args)
                payload = "\n".join(
                    getattr(c, "text", str(c)) for c in result.content
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": payload[:6000],
                })


if __name__ == "__main__":
    asyncio.run(run())
