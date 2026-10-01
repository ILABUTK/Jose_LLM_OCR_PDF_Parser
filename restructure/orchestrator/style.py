"""Style reference extraction.

The author supplies a previous paper (style.tex / style.md / style.pdf / ...).
We derive a compact STYLE GUIDE from it that the writing agent mimics — voice,
hedging, sentence rhythm, citation habits. Cached to $OUTPUT_DIR/style_guide.txt.
"""
from __future__ import annotations

import config
from llm_client import complete

_cache: str | None = None
_GUIDE = config.OUTPUT_DIR / "style_guide.txt"

_SYS = (
    "You analyse an author's writing sample and produce a concise STYLE GUIDE "
    "(<= 250 words) another writer can follow: voice, person, hedging, typical "
    "sentence length, how evidence is framed, transition habits, and citation "
    "style. Output plain text bullet points."
)


def _read_style_text() -> str:
    p = config.style_reference_path()
    if p is None:
        return ""
    if p.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(p))
            return "\n".join((pg.extract_text() or "") for pg in reader.pages[:8])
        except Exception:
            return ""
    return p.read_text(encoding="utf-8", errors="ignore")


def style_summary() -> str:
    global _cache
    if _cache is not None:
        return _cache
    if _GUIDE.exists():
        _cache = _GUIDE.read_text(encoding="utf-8")
        return _cache
    raw = _read_style_text()
    if not raw.strip():
        _cache = ("No style reference provided. Use a formal, impersonal "
                  "scientific review voice with measured hedging and dense citations.")
    else:
        try:
            _cache = complete(_SYS, raw[:12000], temperature=0.2, max_tokens=600)
        except Exception as e:
            _cache = f"(style extraction failed: {e}) Use formal scientific review voice."
    _GUIDE.write_text(_cache, encoding="utf-8")
    return _cache
