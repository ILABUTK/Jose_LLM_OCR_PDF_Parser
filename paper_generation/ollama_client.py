"""Authenticated client for the remote Ollama server (Viridian).

Wraps the standard `/api/chat` and `/api/embeddings` endpoints with HTTP
Basic auth. Exposes:
    chat(model, messages, **opts)        -> assistant text
    chat_json(model, messages, **opts)   -> dict (forces format=json)
    embed(model, text)                   -> list[float]
"""
from __future__ import annotations
import json
from typing import Any, Iterable
import requests
from requests.auth import HTTPBasicAuth

from config import OLLAMA_HOST, OLLAMA_USERNAME, OLLAMA_PASSWORD

_AUTH = HTTPBasicAuth(OLLAMA_USERNAME, OLLAMA_PASSWORD)
# Per-token read timeout; the connection streams tokens continuously so the
# proxy never sees an idle connection long enough to issue a 504.
_CONNECT_TIMEOUT = 60   # seconds to establish connection
_READ_TIMEOUT    = 120  # seconds between successive chunks (tokens)


def chat(
    model: str,
    messages: list[dict],
    *,
    temperature: float = 0.2,
    num_predict: int = 2048,
    format: str | None = None,
    extra: dict | None = None,
    max_retries: int = 5,
    think: bool | None = None,
) -> str:
    """Streaming chat — keeps connection alive token-by-token to avoid 504s.
    Returns the full assembled assistant text. Retries on 502/503/504/timeout.

    think:
        None  → leave default (thinking models reason before answering)
        False → disable reasoning phase (saves tokens; use for prose generation)
        True  → force reasoning phase
    """
    import time
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,   # stream tokens → proxy never idles → no 504
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
            **(extra or {}),
        },
    }
    if format:
        payload["format"] = format
    if think is not None:
        payload["think"] = think
    last_exc = None
    for attempt in range(max_retries):
        try:
            r = requests.post(
                f"{OLLAMA_HOST}/api/chat",
                json=payload,
                auth=_AUTH,
                timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
                stream=True,
            )
            if r.status_code in (502, 503, 504):
                last_exc = requests.HTTPError(f"{r.status_code} {r.reason}")
                wait = 15 * (attempt + 1)
                print(f"  [retry {attempt + 1}/{max_retries}] {r.status_code} — backing off {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            # Accumulate streamed JSON lines.
            # qwen3 thinking models emit tokens via message.thinking (reasoning
            # phase) before emitting message.content (answer phase).  We
            # reconstruct the <think>…</think> wrapper so that chat_json's
            # existing stripping logic works unchanged.
            thinking_chunks: list[str] = []
            content_chunks: list[str] = []
            for line in r.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                msg = data.get("message", {})
                t = msg.get("thinking", "")
                c = msg.get("content", "")
                if t:
                    thinking_chunks.append(t)
                if c:
                    content_chunks.append(c)
                if data.get("done"):
                    break
            think_block = (
                "<think>" + "".join(thinking_chunks) + "</think>\n"
                if thinking_chunks else ""
            )
            return think_block + "".join(content_chunks)
        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            wait = 15 * (attempt + 1)
            print(f"  [retry {attempt + 1}/{max_retries}] {e!r} — backing off {wait}s")
            time.sleep(wait)
    raise last_exc or RuntimeError("chat failed without exception")


def chat_json(model: str, messages: list[dict], **kw) -> dict:
    """Chat with format=json; parses and returns the dict.
    Robust to: code fences, <think> tags, prose before/after JSON.
    Retries with doubled num_predict if the model only produces thinking tokens
    and no JSON content (common with qwen3 thinking models)."""
    import re as _re

    # Start with caller-supplied num_predict (default 2048) and double on each
    # empty-response retry so thinking models have enough budget for the answer.
    base_predict = kw.pop("num_predict", 2048)
    max_json_retries = 3

    for json_attempt in range(max_json_retries):
        cur_predict = base_predict * (2 ** json_attempt)
        raw = chat(model, messages, format="json", num_predict=cur_predict, **kw)
        raw = raw.strip()
        # Strip <think>...</think> blocks (qwen3 thinking models)
        raw = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
        # Strip ```json fences
        raw = _re.sub(r"^```(?:json)?\s*", "", raw)
        raw = _re.sub(r"\s*```$", "", raw)
        raw = raw.strip()
        if not raw.startswith("{") and not raw.startswith("["):
            start_obj = raw.find("{")
            start_arr = raw.find("[")
            starts = [s for s in (start_obj, start_arr) if s >= 0]
            if not starts:
                print(f"  [chat_json] empty response on attempt {json_attempt+1}/{max_json_retries} "
                      f"(num_predict={cur_predict}) — retrying with doubled budget")
                continue
            start = min(starts)
            end_obj = raw.rfind("}")
            end_arr = raw.rfind("]")
            end = max(end_obj, end_arr)
            raw = raw[start : end + 1]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            print(f"  [chat_json] JSON decode error on attempt {json_attempt+1}/{max_json_retries} — retrying")
            continue

    raise ValueError(f"No valid JSON after {max_json_retries} attempts (last raw[:200]: {raw[:200]})") 


def embed(model: str, text: str) -> list[float]:
    r = requests.post(
        f"{OLLAMA_HOST}/api/embeddings",
        json={"model": model, "prompt": text},
        auth=_AUTH,
        timeout=(_CONNECT_TIMEOUT, 120),
    )
    r.raise_for_status()
    return r.json()["embedding"]


def list_models() -> list[str]:
    r = requests.get(f"{OLLAMA_HOST}/api/tags", auth=_AUTH, timeout=(_CONNECT_TIMEOUT, 30))
    r.raise_for_status()
    return [m["name"] for m in r.json().get("models", [])]


if __name__ == "__main__":
    # Smoke test
    print("Reachable. Models on server:")
    for m in list_models():
        print(" -", m)
