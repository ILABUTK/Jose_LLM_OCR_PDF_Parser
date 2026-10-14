"""OpenAI-compatible client for the external vLLM instance.

The vLLM server exposes the standard `/v1/chat/completions` endpoint (the
`llmlite` custom endpoint, model `ornl-qwen3-8-27b`). We talk to it with plain
`requests` so there is no hard dependency on a specific `openai` SDK version,
and so tool-calling payloads can be passed through verbatim.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests

from config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_OUTPUT_TOKENS,
    LLM_MODEL,
    LLM_TEMPERATURE,
    OUTPUT_DIR,
)

_CONNECT_TIMEOUT = 60
_READ_TIMEOUT = 300
_RETRYABLE = {408, 429, 500, 502, 503, 504}

# Every prompt + reply is appended here so runs are fully auditable and the
# live viewer can tail the conversation in real time.
_CALL_LOG = OUTPUT_DIR / "llm_calls.jsonl"


def _log_call(payload: dict, message: dict, elapsed: float) -> None:
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": payload["model"],
        "elapsed_s": round(elapsed, 2),
        "request": payload["messages"],
        "response": message,
    }
    with _CALL_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }


def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
    max_retries: int = 5,
) -> dict:
    """Return the full assistant *message* object.

    When `tools` is supplied the returned message may contain `tool_calls`
    instead of (or in addition to) `content` — this is what the MCP agent loop
    consumes.
    """
    payload: dict[str, Any] = {
        "model": model or LLM_MODEL,
        "messages": messages,
        "temperature": LLM_TEMPERATURE if temperature is None else temperature,
        "max_tokens": max_tokens or LLM_MAX_OUTPUT_TOKENS,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            started = time.monotonic()
            r = requests.post(
                f"{LLM_BASE_URL.rstrip('/')}/chat/completions",
                headers=_headers(),
                json=payload,
                timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
            )
            if r.status_code in _RETRYABLE:
                last_exc = requests.HTTPError(f"{r.status_code} {r.reason}")
                wait = 10 * (attempt + 1)
                print(f"  [llm retry {attempt + 1}/{max_retries}] {r.status_code} — {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            message = r.json()["choices"][0]["message"]
            _log_call(payload, message, time.monotonic() - started)
            return message
        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            wait = 10 * (attempt + 1)
            print(f"  [llm retry {attempt + 1}/{max_retries}] {e!r} — {wait}s")
            time.sleep(wait)
    raise last_exc or RuntimeError("chat failed without exception")


def complete(
    system: str,
    user: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    think: bool = False,
) -> str:
    """Convenience single-turn helper returning assistant text.

    `think=False` strips any <think>…</think> reasoning block that qwen-style
    models emit, returning only the final answer.
    """
    msg = chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    text = msg.get("content") or ""
    if not think:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    return text.strip()


def complete_json(system: str, user: str, **kw) -> Any:
    """Single-turn helper that parses a JSON object/array from the reply.

    Robust to code fences, <think> wrappers, and prose around the JSON.
    """
    raw = complete(system, user + "\n\nRespond with ONLY valid JSON.", **kw)
    raw = re.sub(r"```(?:json)?", "", raw).strip()
    if not (raw.startswith("{") or raw.startswith("[")):
        s_obj, s_arr = raw.find("{"), raw.find("[")
        starts = [s for s in (s_obj, s_arr) if s >= 0]
        if starts:
            start = min(starts)
            end = max(raw.rfind("}"), raw.rfind("]"))
            raw = raw[start : end + 1]
    return json.loads(raw)


if __name__ == "__main__":
    print("LLM smoke test against", LLM_BASE_URL, "model", LLM_MODEL)
    print(complete("You are terse.", "Reply with the single word: ready"))
