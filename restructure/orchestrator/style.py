"""Style reference extraction.

The author supplies a previous paper (style.tex / style.md / style.pdf / ...).
We derive a compact STYLE GUIDE from it that the writing agent mimics — voice,
hedging, sentence rhythm, citation habits. The qualitative guide (LLM) is
augmented with deterministic stylometric metrics (textstat + stdlib) so the
writer gets concrete, numeric targets. Cached to $OUTPUT_DIR/style_guide.txt.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter

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

_HEDGES = {
    "may", "might", "could", "suggest", "suggests", "indicate", "indicates",
    "appear", "appears", "likely", "possibly", "potential", "tend", "tends",
    "propose", "proposes", "observe", "observed", "demonstrate", "demonstrates",
}
_PASSIVE_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being)\s+\w+(?:ed|en)\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z']+")


def _clean_prose(text: str) -> str:
    """Strip MinerU/markdown artefacts (math, tables, images, headings) so the
    stylometry reflects the author's prose, not LaTeX noise."""
    text = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.DOTALL)   # display math
    text = re.sub(r"\$[^$]*\$", " ", text)                        # inline math
    text = re.sub(r"\\[a-zA-Z]+", " ", text)                      # LaTeX commands
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)            # images
    text = re.sub(r"<[^>]+>", " ", text)                          # html tags
    lines = [ln for ln in text.splitlines()
             if not ln.lstrip().startswith(("#", "|", "!", "$"))]  # headings/tables
    return "\n".join(lines)


def _stylometry(text: str) -> str:
    """Deterministic style fingerprint appended to the LLM style guide."""
    import textstat

    text = _clean_prose(text)
    sents = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    sent_word_counts = [len(_WORD_RE.findall(s)) for s in sents]
    # Keep plausible prose sentences for the length stat (drop equation shards
    # and runaway non-punctuated blocks).
    sent_word_counts = [c for c in sent_word_counts if 3 <= c <= 60]
    words = _WORD_RE.findall(text)
    if not words or not sent_word_counts:
        return ""

    lower = [w.lower() for w in words]
    ttr = len(set(lower)) / len(lower)
    avg_sent = statistics.mean(sent_word_counts)
    sd_sent = statistics.pstdev(sent_word_counts) if len(sent_word_counts) > 1 else 0.0
    avg_word_len = statistics.mean(len(w) for w in words)
    hedge_rate = 1000 * sum(1 for w in lower if w in _HEDGES) / len(lower)
    passive = len(_PASSIVE_RE.findall(text))
    passive_rate = 100 * passive / len(sents)
    common = ", ".join(w for w, _ in Counter(
        w for w in lower if len(w) > 3).most_common(8))

    return (
        "STYLOMETRIC TARGETS (match these):\n"
        f"- Sentence length: {avg_sent:.0f} \u00b1 {sd_sent:.0f} words\n"
        f"- Avg word length: {avg_word_len:.1f} chars\n"
        f"- Readability: Flesch {textstat.flesch_reading_ease(text):.0f}, "
        f"Flesch-Kincaid grade {textstat.flesch_kincaid_grade(text):.1f}, "
        f"Gunning fog {textstat.gunning_fog(text):.1f}\n"
        f"- Lexical diversity (type-token ratio): {ttr:.2f}\n"
        f"- Hedging rate: {hedge_rate:.1f} per 1000 words\n"
        f"- Passive constructions: ~{passive_rate:.0f}% of sentences\n"
        f"- Frequent content words: {common}"
    )


def _read_style_text() -> str:
    p = config.style_reference_path()
    if p is None:
        raise SystemExit(
            "No style reference found. Provide a previous paper by the author "
            "(inputs/style.* or a MinerU-parsed paper under inputs/style/)."
        )
    if p.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(p))
        return "\n".join((pg.extract_text() or "") for pg in reader.pages[:8])
    return p.read_text(encoding="utf-8", errors="ignore")


def style_summary() -> str:
    global _cache
    if _cache is not None:
        return _cache
    # Only trust a cache file that actually has content (a stale empty file
    # from a prior failed run must not suppress extraction).
    if _GUIDE.exists() and _GUIDE.read_text(encoding="utf-8").strip():
        _cache = _GUIDE.read_text(encoding="utf-8")
        return _cache
    raw = _read_style_text()
    if not raw.strip():
        raise SystemExit("Style reference is empty — provide a readable author paper.")
    guide = complete(_SYS, raw[:12000], temperature=0.2, max_tokens=600)
    _cache = guide + "\n\n" + _stylometry(raw)
    _GUIDE.write_text(_cache, encoding="utf-8")
    return _cache
