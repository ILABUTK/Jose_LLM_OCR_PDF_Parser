"""Central configuration for the restructured paper-generation pipeline.

Everything is driven by environment variables so the whole stack can be
configured from a single docker-compose / .env file.

Inputs (mounted read-only at $INPUT_DIR):
    hypothesis.json   research hypothesis
    keywords.json     keyword list
    style.(tex|md|pdf|txt)  a previous paper by the author (style reference)
    pdfs/             folder with the corpus PDFs
    *.bib / *.enw / *.ris   references (BibTeX or EndNote/RIS)

Outputs are written to $OUTPUT_DIR.
"""
from __future__ import annotations

import os
from pathlib import Path


def _env(key: str, default: str) -> str:
    v = os.environ.get(key, "").strip()
    return v if v else default


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    return int(raw) if raw else default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    return float(raw) if raw else default


# ── LLM engine (external vLLM, OpenAI-compatible) ────────────────────────────
# We only *connect* to a pre-provisioned vLLM instance — it is NOT part of the
# docker-compose stack. The endpoint below mirrors the `llmlite` custom
# endpoint definition (ornl-qwen3-8-27b served by vLLM, behind ngrok).
LLM_BASE_URL = _env("LLM_BASE_URL", "https://75e4-160-36-103-252.ngrok-free.app/v1")
LLM_MODEL = _env("LLM_MODEL", "ornl-qwen3-8-27b")
LLM_API_KEY = _env("LLM_API_KEY", "not-needed")
LLM_MAX_INPUT_TOKENS = _env_int("LLM_MAX_INPUT_TOKENS", 32000)
LLM_MAX_OUTPUT_TOKENS = _env_int("LLM_MAX_OUTPUT_TOKENS", 8000)
LLM_TEMPERATURE = _env_float("LLM_TEMPERATURE", 0.3)

# ── Graph-based reasoning ────────────────────────────────────────────────────
# How deep the chain-of-thought graph expands at every node. Each node is
# generated, then compared / validated / delved into GRAPH_DEPTH levels deep.
GRAPH_DEPTH = _env_int("GRAPH_DEPTH", 3)
# How many child ideas each node spawns while delving.
GRAPH_BRANCHING = _env_int("GRAPH_BRANCHING", 3)

# ── Figure generation (LLM-drawn SVG — no external service) ────────────────
# Number of SVG figures generated per developed idea / graph node.
PAPER_IMAGE_COUNT = _env_int("PAPER_IMAGE_COUNT", 2)
# Token budget for a single SVG generation call.
SVG_MAX_TOKENS = _env_int("SVG_MAX_TOKENS", 6000)

# ── Paths ────────────────────────────────────────────────────────────────────
INPUT_DIR = Path(_env("INPUT_DIR", "/inputs"))
OUTPUT_DIR = Path(_env("OUTPUT_DIR", "/outputs"))

HYPOTHESIS_JSON = INPUT_DIR / "hypothesis.json"
KEYWORDS_JSON = INPUT_DIR / "keywords.json"
PDF_DIR = INPUT_DIR / "pdfs"

# style reference is auto-detected (first match wins)
STYLE_CANDIDATES = ["style.tex", "style.md", "style.txt", "style.pdf"]
# ...or a whole MinerU-parsed paper dropped under inputs/style/
STYLE_DIR = INPUT_DIR / "style"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
FIGURES_DIR = OUTPUT_DIR / "figures"
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

GRAPH_JSON = OUTPUT_DIR / "reasoning_graph.json"
DRAFT_JSON = OUTPUT_DIR / "draft_sections.json"
PAPER_MD = OUTPUT_DIR / "paper.md"
PAPER_TEX = OUTPUT_DIR / "paper.tex"
PAPER_PDF = OUTPUT_DIR / "paper.pdf"


def style_reference_path() -> Path | None:
    # 1) an explicit style.* file at the input root
    for name in STYLE_CANDIDATES:
        p = INPUT_DIR / name
        if p.exists():
            return p
    # 2) a MinerU-parsed paper folder under inputs/style/ — take its .md
    if STYLE_DIR.is_dir():
        mds = sorted(p for p in STYLE_DIR.rglob("*.md")
                     if p.name.lower() != "readme.md")
        if mds:
            return mds[0]
    return None
