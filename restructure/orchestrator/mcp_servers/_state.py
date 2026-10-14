"""Shared, lazily-initialised state for the MCP agent servers.

All four MCP servers (corpus, reasoning, image, writing) operate on the same
in-memory corpus. Loading PDFs is expensive, so we build it once per process
and cache it here.
"""
from __future__ import annotations

import json

import config
from corpus import Corpus, load_corpus

_corpus: Corpus | None = None


def corpus() -> Corpus:
    global _corpus
    if _corpus is None:
        _corpus = load_corpus()
    return _corpus


def hypothesis() -> dict:
    if not config.HYPOTHESIS_JSON.exists():
        raise SystemExit(f"Missing {config.HYPOTHESIS_JSON} — provide a research hypothesis.")
    return json.loads(config.HYPOTHESIS_JSON.read_text(encoding="utf-8"))


def keywords() -> list[str]:
    if not config.KEYWORDS_JSON.exists():
        raise SystemExit(f"Missing {config.KEYWORDS_JSON} — provide keywords.")
    data = json.loads(config.KEYWORDS_JSON.read_text(encoding="utf-8"))
    return data["keywords"] if isinstance(data, dict) else data
