"""05 — Render the assembled draft into Elsevier LaTeX (elsarticle.cls).

Pure-Python markdown → LaTeX conversion (no LLM calls).
Strips <think> reasoning blocks, converts citations, headings, tables,
bold/italic, and common unicode chemistry symbols.

Output: output/paper.tex
Compile: cd output && pdflatex paper && bibtex paper && pdflatex paper && pdflatex paper
"""
from __future__ import annotations
import json
import re
import shutil
from pathlib import Path

from config import (
    OUTLINE_JSON,
    DRAFT_SECTIONS,
    ELSEVIER_TEX,
    OUTPUT_DIR,
    PAPER_TITLE,
    PAPER_JOURNAL,
    PAPER_AUTHORS,
    PAPER_AFFILIATIONS,
    PAPER_FUNDING_TEXT,
    PAPER_ACK_TEXT,
    PAPER_CREDIT_TEXT,
    PAPER_DECLARATION_TEXT,
    PAPER_DATA_AVAILABILITY_TEXT,
)
from corpus import load_bib_index, load_figure_catalog, load_corpus

# Re-use the writer's evidence-bank retrieval so we can map writer-emitted
# numeric refs (e.g. "[1]", "[2]") back to the actual citekey of the i-th
# evidence entry — qwen3 reliably emits [N] instead of [citekey].
try:
    from importlib import import_module
    _agents_mod = import_module("03_agents_write")  # filename starts with digit
    _retrieve_evidence_bank = _agents_mod.retrieve_evidence_bank
except Exception:
    _retrieve_evidence_bank = None

# ── LaTeX section-level commands ─────────────────────────────────────────────
_LEVEL_CMDS = {
    0: r"\section*",      # unnumbered  (Highlights, Funding, …)
    1: r"\section",       # 1. Introduction
    2: r"\subsection",    # 2.1. …
    3: r"\subsubsection", # 2.1.1. …
    4: r"\paragraph",
}

# ── Unicode → LaTeX lookup table ─────────────────────────────────────────────
_SUBSCRIPT_TBL   = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_SUPERSCRIPT_TBL = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")

_UNICODE_SUBS = [
    # chemistry / physics
    ("°",  r"$^{\circ}$"),
    ("μ",  r"$\mu$"),
    ("·",  r"$\cdot$"),
    ("×",  r"$\times$"),
    ("≥",  r"$\geq$"),
    ("≤",  r"$\leq$"),
    ("≈",  r"$\approx$"),
    ("∼",  r"$\sim$"),
    ("→",  r"$\rightarrow$"),
    ("←",  r"$\leftarrow$"),
    ("±",  r"$\pm$"),
    # subscripts / superscripts
    ("\u2080", r"$_{0}$"), ("\u2081", r"$_{1}$"), ("\u2082", r"$_{2}$"),
    ("\u2083", r"$_{3}$"), ("\u2084", r"$_{4}$"), ("\u2085", r"$_{5}$"),
    ("\u2086", r"$_{6}$"), ("\u2087", r"$_{7}$"), ("\u2088", r"$_{8}$"),
    ("\u2089", r"$_{9}$"),
    ("\u2070", r"$^{0}$"), ("\u00b9", r"$^{1}$"), ("\u00b2", r"$^{2}$"),
    ("\u00b3", r"$^{3}$"), ("\u2074", r"$^{4}$"), ("\u2075", r"$^{5}$"),
    ("\u2076", r"$^{6}$"), ("\u2077", r"$^{7}$"), ("\u2078", r"$^{8}$"),
    ("\u2079", r"$^{9}$"),
    # punctuation
    ("\u2013", "-"),    # en dash -> simple hyphen
    ("\u2014", "-"),    # em dash -> simple hyphen
    ("\u2015", "-"),    # horizontal bar -> simple hyphen
    ("\u2019", "'"),
    ("\u2018", "`"),
    ("\u201d", "''"),
    ("\u201c", "``"),
    ("\u00b7", r"$\cdot$"),
    # whitespace variants → regular space
    ("\u00a0", " "),    # non-breaking space
    ("\u202f", " "),    # narrow no-break space
    ("\u2009", " "),    # thin space
    ("\u200b", ""),     # zero-width space
    ("\u2060", ""),     # word joiner
    ("\ufeff", ""),     # BOM
    # arrows / misc
    ("\u21d2", r"$\Rightarrow$"),
    ("\u21d0", r"$\Leftarrow$"),
    # Greek (commonly seen in chemistry)
    ("\u03b1", r"$\alpha$"), ("\u03b2", r"$\beta$"), ("\u03b3", r"$\gamma$"),
    ("\u03b4", r"$\delta$"), ("\u03b5", r"$\varepsilon$"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _split_math(text: str):
    """Split text into alternating (non-math, math) chunks.

    Yields (chunk, is_math) pairs so we can skip math regions.
    Handles both $...$ and $$...$$ delimiters.
    """
    pattern = re.compile(r'\$\$.*?\$\$|\$[^$\n]+?\$', re.DOTALL)
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            yield text[pos:m.start()], False
        yield m.group(), True
        pos = m.end()
    if pos < len(text):
        yield text[pos:], False


def _apply_outside_math(text: str, fn) -> str:
    """Apply fn to non-math segments only."""
    return "".join(fn(chunk) if not is_math else chunk
                   for chunk, is_math in _split_math(text))


def _unicode_to_latex(text: str) -> str:
    """Convert unicode chars to LaTeX equivalents, skipping math regions."""
    def process(chunk: str) -> str:
        # Subscript digits: ₂ → $_{2}$
        for c in "₀₁₂₃₄₅₆₇₈₉":
            if c in chunk:
                chunk = chunk.replace(c, f'$_{{{c.translate(_SUBSCRIPT_TBL)}}}$')
        # Superscript digits: ² → $^{2}$
        for c in "⁰¹²³⁴⁵⁶⁷⁸⁹":
            if c in chunk:
                chunk = chunk.replace(c, f'$^{{{c.translate(_SUPERSCRIPT_TBL)}}}$')
        for src, dst in _UNICODE_SUBS:
            chunk = chunk.replace(src, dst)
        # Final safety net: replace any remaining non-ASCII char with '?' to
        # avoid pdflatex U+XXXX fatal errors. Keep common LaTeX-safe chars.
        chunk = "".join(c if (ord(c) < 128 or c in "$\\{}_^") else "?" for c in chunk)
        return chunk
    return _apply_outside_math(text, process)


def _escape_percent(text: str) -> str:
    """Escape bare % as \\% outside math mode."""
    def process(chunk: str) -> str:
        return re.sub(r'(?<!\\)%', r'\\%', chunk)
    return _apply_outside_math(text, process)


def strip_think(text: str) -> str:
    """Remove <think>…</think> reasoning blocks produced by qwen3."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _base_level(title: str) -> int:
    """Infer LaTeX section depth from the section title numbering.

    "2.1.3. Title" → 3  (\\subsubsection)
    "2.1. Title"   → 2  (\\subsection)
    "2. Title"     → 1  (\\section)
    "Highlights"   → 0  (\\section*)
    """
    if re.match(r"^\d+\.\d+\.\d+\.?\s", title):
        return 3
    if re.match(r"^\d+\.\d+\.?\s", title):
        return 2
    if re.match(r"^\d+\.?\s", title):
        return 1
    return 0


def _clean_heading(title: str) -> str:
    """Strip numeric prefix (e.g., '2.1. ') from a heading."""
    return re.sub(r"^(\d+\.)*\d*\.?\s*", "", title.strip()).strip()


def _convert_table(lines: list[str]) -> str:
    """Convert markdown table lines → LaTeX tabular."""
    rows: list[list[str]] = []
    for ln in lines:
        if re.match(r"^\s*\|[-: |]+\|\s*$", ln):
            continue  # separator row — skip
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return ""
    ncols = max(len(r) for r in rows)

    def _cell(c: str) -> str:
        c = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", c)
        c = re.sub(r"\*(.+?)\*",     r"\\textit{\1}", c)
        c = re.sub(r"\[(RN\d+|\d{3,}|1-s2\.0-[^\]]+|[a-z][a-z0-9_]*_\d{4})\]", r"\\citep{\1}", c)
        return c

    latex_rows: list[str] = []
    for i, row in enumerate(rows):
        while len(row) < ncols:
            row.append("")
        latex_rows.append(" & ".join(_cell(c) for c in row) + r" \\")
        if i == 0:
            latex_rows.append(r"\hline")

    col_spec = "l" * ncols
    return (
        "\n\\begin{table}[htb]\n"
        "\\centering\n"
        f"\\begin{{tabular}}{{{col_spec}}}\n"
        "\\hline\n"
        + "\n".join(latex_rows) + "\n"
        "\\hline\n"
        "\\end{tabular}\n"
        "\\end{table}\n"
    )


# Maps rel_path basename → figures/dest.jpg  (populated during render)
_FIGURE_MAP: dict[str, str] = {}


def _parse_braced(s: str, start: int) -> tuple[str, int] | None:
    """Parse a brace-balanced group starting at s[start] == '{'.
    Returns (content, index_after_closing_brace) or None on failure."""
    if start >= len(s) or s[start] != "{":
        return None
    depth = 0
    i = start
    while i < len(s):
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start + 1:i], i + 1
        i += 1
    return None


def _resolve_figure_tags(text: str) -> str:
    """Find all \\FIGURE{citekey}{rel_path}{caption} occurrences and replace
    them, handling brace-balanced captions (which may contain math like
    ``$\\mathrm{Li_2O}$``)."""
    out = []
    i = 0
    while i < len(text):
        idx = text.find("\\FIGURE{", i)
        if idx < 0:
            out.append(text[i:])
            break
        out.append(text[i:idx])
        # parse three braced groups
        p1 = _parse_braced(text, idx + len("\\FIGURE"))
        if p1 is None:
            out.append(text[idx:idx + 8])
            i = idx + 8
            continue
        g1, j = p1
        p2 = _parse_braced(text, j)
        if p2 is None:
            out.append(text[idx:j])
            i = j
            continue
        g2, k = p2
        p3 = _parse_braced(text, k)
        if p3 is None:
            out.append(text[idx:k])
            i = k
            continue
        g3, end = p3

        class _Fake:
            def __init__(self, a, b, c):
                self._g = (None, a, b, c)
            def group(self, n):
                return self._g[n]

        out.append(_resolve_figure_tag(_Fake(g1, g2, g3)))
        i = end
    return "".join(out)


def _resolve_figure_tag(m: re.Match) -> str:
    """Convert \\FIGURE{citekey}{rel_path}{caption} → LaTeX figure float."""
    citekey  = m.group(1).strip()
    rel_path = m.group(2).strip()
    caption  = m.group(3).strip()
    # Reject obviously malformed citekeys (e.g. LLM emitted "fig:xxxx" by mistake)
    if citekey.startswith(("fig:", "Fig:", "FIG:")) or ":" in citekey:
        return ""   # drop the figure tag entirely; it cannot be resolved
    # Convert Unicode in caption now (it will not be re-processed later)
    caption  = _unicode_to_latex(caption)
    # Clean caption: convert inline citations
    caption  = re.sub(r"\[(RN\d+|\d{3,}|1-s2\.0-[^\]]+|[a-z][a-z0-9_]*_\d{4})\]", r"\\citep{\1}", caption)
    # If caption already cites the source, do not append another \cite
    already_cited = bool(re.search(r"\\cite[pt]?\{[^}]*" + re.escape(citekey) + r"[^}]*\}", caption))
    citation_suffix = "" if already_cited else f" \\citep{{{citekey}}}"
    # Filename in figures/ dir
    basename = Path(rel_path).name
    dest_name = f"{citekey}_{basename}"
    if dest_name in _FIGURE_MAP:
        tex_path = _FIGURE_MAP[dest_name]
    else:
        # File not copied/known — skip the float to avoid pdflatex "File not found"
        return ""
    return (
        f"\n\\begin{{figure}}[htb]\n"
        f"  \\centering\n"
        f"  \\includegraphics[width=0.85\\textwidth]{{{tex_path}}}\n"
        f"  \\caption{{{caption}{citation_suffix}}}\n"
        f"  \\label{{fig:{dest_name.replace('.', '_')}}}\n"
        f"\\end{{figure}}\n"
    )


def _annotate_claims_with_color(tex: str, claim_scores: list[dict]) -> str:
    """Wrap sentences in the LaTeX body with confidence tier colors.

    Colors (defined in preamble):
      highconf  (green)  : grounding >= 0.75
      medconf   (amber)  : 0.55 <= grounding < 0.75
      lowconf   (red)    : grounding < 0.55

    Strategy: for each scored claim we look up its (stripped) plain text in
    the LaTeX output and wrap the surrounding sentence-span in \\textcolor.
    Only plain-text paragraphs are annotated; headings, tables, figures, and
    math environments are left untouched.
    """
    if not claim_scores:
        return tex

    # Build a fast lookup: stripped plain text -> color
    _COLOR_MAP = {"high": "highconf", "medium": "medconf", "low": "lowconf"}
    lookup: list[tuple[str, str]] = []
    for c in claim_scores:
        raw = c.get("text", "").strip()
        tier = c.get("confidence_tier", "medium")
        if len(raw) > 20:
            lookup.append((raw, _COLOR_MAP.get(tier, "medconf")))

    # Sentence splitter (same regex as validate): split on ". " before capital
    _SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\\[])")

    # Only annotate lines that look like running prose (not headings/env lines)
    _SKIP_LINE  = re.compile(
        r"^\s*(?:\\section|\\subsection|\\subsubsection|\\paragraph|"
        r"\\begin|\\end|\\label|\\caption|\\item|\\cite|%|\\toprule|"
        r"\\midrule|\\bottomrule|\\hline|\$\$|&)"
    )

    lines = tex.split("\n")
    new_lines: list[str] = []
    for line in lines:
        if _SKIP_LINE.match(line):
            new_lines.append(line)
            continue
        # Check if any claim text appears in this line; if so, wrap sentence
        matched = False
        for plain_text, color in lookup:
            # Use first ~60 chars as key to avoid regex size issues
            key = re.escape(plain_text[:60])
            if re.search(key, line):
                # Wrap whole line in color (sentence-level granularity)
                line = f"\\textcolor{{{color}}}{{{line}}}"
                matched = True
                break
        new_lines.append(line)
    return "\n".join(new_lines)


def md_to_latex(md: str, section_title: str) -> str:
    """Convert a draft_sections.json 'final' field to LaTeX body text."""
    # 1. Strip <think> reasoning
    text = strip_think(md)

    # 2. Remove writer/critic meta-lines
    text = re.sub(r"\*\*Revisions Addressed\*\*.*$", "", text, flags=re.DOTALL | re.MULTILINE)
    text = re.sub(r"^\*\*\(Word count:.*?\)\*\*\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\*Word count:.*?\*\s*$", "",          text, flags=re.MULTILINE)
    text = re.sub(r"^-{3,}\s*$", "",                        text, flags=re.MULTILINE)
    text = re.sub(r"<!--.*?-->", "",                         text, flags=re.DOTALL)

    # 2a. Resolve \FIGURE tags FIRST — before any character substitution that
    #     could inject curly braces and break the regex (e.g. unicode subscripts
    #     -> \textsubscript{2} would smash the brace count).
    # Drop EVIDENCE-NEEDED placeholders and other malformed FIGUREs first.
    text = re.sub(r"\\FIGURE\{EVIDENCE NEEDED\}[^\n]*", "", text)
    text = _resolve_figure_tags(text)

    base = _base_level(section_title)

    # 3. Process line-by-line (headings + tables)
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Heading
        hm = re.match(r"^(#{1,6})\s+(.*?)\s*$", line.rstrip())
        if hm:
            depth = len(hm.group(1))
            htitle = hm.group(2).strip()
            level = base + (depth - 1)
            cmd = _LEVEL_CMDS.get(min(level, 4), r"\paragraph")
            # strip numeric prefix only from top-level (#) headings
            clean = _clean_heading(htitle) if depth == 1 else htitle.strip()
            out.append(f"\n{cmd}{{{clean}}}\n")
            i += 1
            continue

        # Markdown table
        if "|" in line and re.match(r"\s*\|", line):
            block: list[str] = []
            while i < len(lines) and "|" in lines[i] and re.match(r"\s*\|", lines[i]):
                block.append(lines[i])
                i += 1
            out.append(_convert_table(block))
            continue

        out.append(line)
        i += 1

    text = "\n".join(out)

    # 4. Citations  [citekey] / [RNxxx] / [<folder-num>] → \cite{citekey}
    text = re.sub(r"\[(RN\d+|\d{3,}|1-s2\.0-[^\]]+|[a-z][a-z0-9_]*_\d{4})\]", r"\\citep{\1}", text)
    text = re.sub(r"\[(1-s2\.0-[^\]]+)\]",  r"\\citep{\1}", text)
    # Merge adjacent \cite{a}\cite{b} → \cite{a,b}  (up to 4 merges)
    for _ in range(4):
        text = re.sub(r"\\citep\{([^}]+)\}\\citep\{([^}]+)\}", r"\\citep{\1,\2}", text)

    # 5. Bold / italic (skip math regions)
    def _inline_markup(chunk: str) -> str:
        chunk = re.sub(r"\*\*\*(.+?)\*\*\*", r"\\textbf{\\textit{\1}}", chunk)
        chunk = re.sub(r"\*\*(.+?)\*\*",     r"\\textbf{\1}",           chunk)
        chunk = re.sub(r"\*([^*\n]+?)\*",    r"\\textit{\1}",           chunk)
        return chunk
    text = _apply_outside_math(text, _inline_markup)

    # 6. Unicode → LaTeX
    text = _unicode_to_latex(text)

    # 7. Escape bare % outside math
    text = _escape_percent(text)

    # 8. Inline code → \texttt
    text = re.sub(r"`([^`\n]+)`", r"\\texttt{\1}", text)

    # 9. \FIGURE{citekey}{rel_path}{caption} → LaTeX figure environment
    text = _resolve_figure_tags(text)

    # 10. Kill any surviving malformed \FIGURE{...} directives (e.g. writer
    #     emitted only 2 braces). They would crash LaTeX as undefined control sequences.
    while True:
        m = re.search(r"\\FIGURE\{", text)
        if not m:
            break
        # Find brace-balanced range and strip everything up to matching close
        i, depth = m.end(), 1
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        # Strip optional trailing {...} groups (additional malformed args)
        while i < len(text) and text[i] == "{":
            i += 1
            depth = 1
            while i < len(text) and depth:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                i += 1
        text = text[:m.start()] + text[i:]

    # 11. Escape stray '&' that are NOT inside a \begin{tabular}…\end{tabular}
    def _escape_ampersand(t: str) -> str:
        out = []
        idx = 0
        # Build list of (start,end) tabular regions to skip
        regions = []
        for tm in re.finditer(r"\\begin\{tabular\}.*?\\end\{tabular\}", t, re.DOTALL):
            regions.append((tm.start(), tm.end()))
        for i, ch in enumerate(t):
            in_region = any(s <= i < e for s, e in regions)
            if ch == "&" and not in_region:
                # don't double-escape
                if i > 0 and t[i - 1] == "\\":
                    out.append(ch)
                else:
                    out.append(r"\&")
            else:
                out.append(ch)
        return "".join(out)
    text = _escape_ampersand(text)

    return text.strip()


# ── BibTeX builder ────────────────────────────────────────────────────────────

def _provenance_badge(section: dict) -> str:
    """Disabled — evidence-quality badges removed by user request."""
    return ""


def _build_provenance_appendix(sections: list[dict]) -> str:
    """Disabled — provenance appendix removed by user request."""
    return ""


def _resolve_key_from_md(key: str) -> dict:
    """For keys not in the bib index (e.g. 1-s2.0-* folder names),
    extract a minimal metadata dict from the parsed markdown title line."""
    from corpus import PARSED
    md_path = PARSED / key / "auto" / f"{key}.md"
    if not md_path.exists():
        return {}
    try:
        text = md_path.read_text(encoding="utf-8", errors="replace")
        # First non-empty line is typically the title
        title = next((l.lstrip("#").strip() for l in text.splitlines() if l.strip()), key)
        return {"title": title[:200], "author": "", "journal": "", "year": "", "doi": ""}
    except Exception:
        return {}


def build_references_bib(used_keys: set[str], bib: dict[str, dict]) -> str:
    """Generate a minimal .bib file containing only the cited keys."""
    entries: list[str] = []

    def esc(v: str) -> str:
        # Remove braces, em/en dashes, and other problematic chars for BibTeX
        v = v.replace("{", "").replace("}", "")
        v = v.replace("\u2013", "-").replace("\u2014", "-").replace("\u2015", "-")
        return v

    for k in sorted(used_keys):
        m = bib.get(k)
        if not m:
            # Allow 1-s2.0-* style folder-name keys (OCR'd but no bib entry).
            # All other unresolved keys are dropped — they should have been
            # filtered out upstream.
            if k.startswith("1-s2.0-"):
                m = _resolve_key_from_md(k)
            if not m:
                continue
        entries.append(
            f"@article{{{k},\n"
            f"  title   = {{{esc(m.get('title', ''))}}},\n"
            f"  author  = {{{esc(m.get('author', ''))}}},\n"
            f"  journal = {{{esc(m.get('journal', ''))}}},\n"
            f"  year    = {{{esc(m.get('year', ''))}}},\n"
            f"  doi     = {{{esc(m.get('doi', ''))}}}\n"
            f"}}"
        )
    return "\n\n".join(entries)


# ── LaTeX template ────────────────────────────────────────────────────────────

def _build_preamble() -> str:
    """Generate the elsarticle frontmatter from fixed config constants."""
    # Authors block
    author_lines = []
    for i, (name, email, tag) in enumerate(PAPER_AUTHORS):
        corref = r"\corref{cor1}" if i == 0 else ""
        author_lines.append(f"\\author[{tag}]{{{name}{corref}}}")
        author_lines.append(f"\\ead{{{email}}}")
    if PAPER_AUTHORS:
        author_lines.append(r"\cortext[cor1]{Corresponding author}")

    # Affiliations block
    affil_lines = []
    for tag, info in PAPER_AFFILIATIONS.items():
        affil_lines.append(
            f"\\affiliation[{tag}]{{organization={{{info['organization']}}},\n"
            f"               city={{{info['city']}}},\n"
            f"               state={{{info['state']}}},\n"
            f"               country={{{info['country']}}}}}"
        )

    authors_block   = "\n".join(author_lines)
    affil_block     = "\n".join(affil_lines)

    return (
        r"""\documentclass[review,12pt,a4paper]{elsarticle}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath,amssymb,graphicx,booktabs,hyperref}
\usepackage{natbib}
\usepackage{xcolor}
\usepackage{soul}
\usepackage{enumitem}
\usepackage{url}
\usepackage{siunitx}
\usepackage[version=4]{mhchem}
\bibliographystyle{elsarticle-num}
\graphicspath{{figures/}}
\definecolor{provgray}{gray}{0.94}
\definecolor{highconf}{rgb}{0.0,0.45,0.0}
\definecolor{medconf}{rgb}{0.55,0.35,0.0}
\definecolor{lowconf}{rgb}{0.65,0.0,0.0}

\journal{"""
        + PAPER_JOURNAL
        + r"""}

\begin{document}

\begin{frontmatter}

\title{"""
        + PAPER_TITLE
        + "}\n\n"
        + authors_block + "\n\n"
        + affil_block
        + r"""

\begin{abstract}
%ABSTRACT%
\end{abstract}

\begin{keyword}
tritium breeder \sep solid breeder \sep fusion reactor \sep ceramic materials
\sep lithium orthosilicate \sep \ce{Li2TiO3} \sep \ce{Li2ZrO3}
\end{keyword}

\end{frontmatter}

"""
    )




_POSTAMBLE = r"""

\bibliography{references}

\end{document}
"""


def _copy_figures(sections: list[dict], fig_catalog: list[dict]) -> None:
    """Copy every figure referenced in draft sections to output/figures/.
    Handles both:
      - \\FIGURE{} tags from the OCR corpus (corpus figures)
      - generated_figures paths from 07_generate_figures.py (SVG)
    """
    fig_dir = OUTPUT_DIR / "figures"
    fig_dir.mkdir(exist_ok=True)

    # Build a lookup: (citekey, rel_path) → fig entry
    catalog_map: dict[tuple, dict] = {
        (f["citekey"], f["rel_path"]): f for f in fig_catalog
    }

    for s in sections:
        # 1. Corpus figures referenced via \FIGURE tags in the draft text
        final = s.get("final", "")
        for m in re.finditer(r"\\FIGURE\{([^}]+)\}\{([^}]+)\}\{[^}]+\}", final):
            citekey  = m.group(1).strip()
            rel_path = m.group(2).strip()
            entry    = catalog_map.get((citekey, rel_path))
            if not entry:
                print(f"  [figures] WARNING: {citekey}/{rel_path} not in catalog, skipping")
                continue
            src       = Path(entry["fig_path"])
            dest_name = f"{citekey}_{src.name}"
            dst       = fig_dir / dest_name
            if not dst.exists():
                shutil.copy2(src, dst)
                print(f"  [figures] copied corpus figure {dest_name}")
            _FIGURE_MAP[dest_name] = dest_name

        # 2. LLM-generated SVG figures from 07_generate_figures.py
        for svg_path in s.get("generated_figures", []):
            src = Path(svg_path)
            if not src.exists():
                continue
            # pdflatex cannot read SVG -> convert to PDF in figures/
            pdf_name = src.stem + ".pdf"
            pdf_dst  = fig_dir / pdf_name
            if not pdf_dst.exists():
                try:
                    import cairosvg
                    cairosvg.svg2pdf(url=str(src), write_to=str(pdf_dst))
                    print(f"  [figures] converted SVG -> {pdf_name}")
                except Exception as e:
                    print(f"  [figures] WARNING: SVG->PDF failed for {src.name}: {e}")
                    continue
            _FIGURE_MAP[pdf_name] = pdf_name
            # also store the SVG basename so later lookups by either name work
            _FIGURE_MAP[src.name] = pdf_name


def main() -> None:
    sections = json.loads(DRAFT_SECTIONS.read_text())
    outline_data = json.loads(OUTLINE_JSON.read_text())
    # outline.json may be a dict with 'sections' or a bare list
    if isinstance(outline_data, dict):
        outline_nodes = outline_data.get("sections", [])
        topic = outline_data.get("topic", "Review of Lithium Ceramic Breeder Materials for Fusion Applications")
    else:
        outline_nodes = outline_data
        topic = "Review of Lithium Ceramic Breeder Materials for Fusion Applications"
    node_by_id = {n["id"]: n for n in outline_nodes if isinstance(n, dict) and "id" in n}
    bib      = load_bib_index()
    fig_catalog = load_figure_catalog(bib_index=bib)

    # ── Drop trailing redundant "Tabulated …" section (duplicate of inline tables)
    sections = [s for s in sections
                if not s["title"].lower().startswith("tabulated ")]

    # ── Rebuild evidence-bank order per section so writer's [1],[2],... refs
    #    can be mapped back to actual citekeys
    print(f"[render] Reconstructing evidence banks for citation rescue …")
    corpus_chunks = None
    if _retrieve_evidence_bank is not None:
        try:
            corpus_chunks = load_corpus(bib_index=bib)
        except Exception as e:
            print(f"  [render] WARNING: could not load corpus for cite-rescue: {e}")

    def _section_ordered_keys(sec: dict) -> list[str]:
        if corpus_chunks is None or _retrieve_evidence_bank is None:
            return []
        node = node_by_id.get(sec["id"]) or {
            "title": sec["title"],
            "directives": [],
            "research_questions": [],
        }
        bank = _retrieve_evidence_bank(corpus_chunks, bib, node)
        # bank format: lines starting with "[citekey] " or "AuthorYear [citekey]"
        keys: list[str] = []
        seen = set()
        for m in re.finditer(r"\[([a-z][a-z0-9_]*_\d{4})\]", bank):
            k = m.group(1)
            if k not in seen:
                seen.add(k)
                keys.append(k)
        return keys

    def _rescue_numeric_cites(sec: dict) -> None:
        """Replace [1], [2], ... in sec['final'] with the actual citekey of the
        Nth entry in the section's evidence bank. Handles ranges like [1-3]
        and comma lists like [1, 2]."""
        ordered = _section_ordered_keys(sec)
        if not ordered:
            return
        text = sec.get("final", "") or ""

        def _lookup(n: int) -> str | None:
            return ordered[n - 1] if 1 <= n <= len(ordered) else None

        def _sub(match: re.Match) -> str:
            body = match.group(1)
            # parse comma-separated nums and/or ranges
            tokens: list[int] = []
            for part in re.split(r"[,;]\s*", body):
                rm = re.match(r"^\s*(\d+)\s*[-–]\s*(\d+)\s*$", part)
                if rm:
                    a, b = int(rm.group(1)), int(rm.group(2))
                    if 1 <= a <= 99 and 1 <= b <= 99 and abs(b - a) < 30:
                        tokens.extend(range(a, b + 1))
                        continue
                nm = re.match(r"^\s*(\d+)\s*$", part)
                if nm:
                    tokens.append(int(nm.group(1)))
                else:
                    return match.group(0)  # unparseable — leave as-is
            keys = [k for n in tokens if (k := _lookup(n))]
            if not keys:
                return match.group(0)
            # dedupe preserving order
            seen, out = set(), []
            for k in keys:
                if k not in seen:
                    seen.add(k); out.append(k)
            return "[" + ",".join(out) + "]"

        # Match plain numeric refs only: [1], [12], [1-3], [1, 2], [1; 3]
        new_text = re.sub(r"\[((?:\s*\d{1,2}\s*[,;\-–]?\s*){1,8})\]", _sub, text)
        sec["final"] = new_text

    for s in sections:
        _rescue_numeric_cites(s)

    print(f"[render] Copying referenced figures …")
    _copy_figures(sections, fig_catalog)

    abstract_tex       = ""
    tail_parts         : list[str] = []   # discarded — replaced by fixed config blocks

    TAIL_ROLES  = {"frontmatter"}
    TAIL_TITLES = {"funding", "acknowledgements", "credit authorship contribution statement",
                   "declaration of competing interest", "data availability"}
    TABLE_TITLE = "tables"

    # section id → rendered tex (body sections only)
    body_tex: dict[str, str] = {}

    for s in sections:
        title = s["title"].strip()
        role  = s.get("role", "")
        final = s.get("final", "")
        tl    = title.lower()

        # Abstract / Highlights → frontmatter abstract block
        if role == "abstract" or tl == "highlights":
            raw = strip_think(final)
            raw = re.sub(r"^#+\s+.*\n?", "", raw, count=1).strip()
            # Strip any \FIGURE tags from the abstract (they would break the float env)
            raw = re.sub(r"\\FIGURE\{[^}]*\}(?:\{[^}]*\})*", "", raw)
            # Also strip raw markdown image syntax
            raw = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", raw)
            # Convert any inline citations
            raw = re.sub(r"\[(RN\d+|\d{3,}|1-s2\.0-[^\]]+|[a-z][a-z0-9_]*_\d{4})\]", r"\\citep{\1}", raw)
            # Convert unicode chars
            raw = _unicode_to_latex(raw)
            abstract_tex = raw
            continue

        print(f"[render] {title}")

        if tl in TAIL_TITLES or (role in TAIL_ROLES and tl not in TABLE_TITLE):
            # Discard LLM-generated tail blocks — we inject fixed UT-Battelle versions later.
            continue

        raw_tex = md_to_latex(final, title)
        claim_scores = s.get("per_claim_scores", [])
        body_tex[s["id"]] = _annotate_claims_with_color(raw_tex, claim_scores)

    # Inject generated SVG figures after each body section
    def _inject_generated_figs(s: dict, tex: str) -> str:
        """Append generated-figure floats after the section body."""
        svg_figs = s.get("generated_figures", [])
        if not svg_figs:
            return tex
        floats = []
        for svg_path in svg_figs:
            name = Path(svg_path).name
            # Use PDF name (cairosvg-converted) when available
            tex_name = _FIGURE_MAP.get(name, name)
            if tex_name not in _FIGURE_MAP and tex_name == name:
                continue
            label = re.sub(r"[^\w]", "_", tex_name)
            floats.append(
                f"\n\\begin{{figure}}[htb]\n"
                f"  \\centering\n"
                f"  \\includegraphics[width=0.90\\textwidth]{{{tex_name}}}\n"
                f"  \\caption{{Synthesised summary figure for: {s['title']}}}\n"
                f"  \\label{{fig:{label}}}\n"
                f"\\end{{figure}}\n"
            )
        return tex + "\n" + "\n".join(floats) if floats else tex

    # Build final body in outline order
    body_parts_final = []
    for s in sections:
        if s["id"] not in body_tex:
            continue
        section_tex = _inject_generated_figs(s, body_tex[s["id"]])
        section_tex += _provenance_badge(s)
        body_parts_final.append(section_tex)

    # Build provenance appendix (from Stage-4 quality_ci annotations)
    prov_appendix = _build_provenance_appendix(
        [s for s in sections if s["id"] in body_tex]
    )

    # Fixed BNT-style tail (Funding / Ack / CRediT / Declaration / Data Availability)
    fixed_tail = (
        "\n\n\\section*{Funding}\n"        + PAPER_FUNDING_TEXT          + "\n"
        "\n\\section*{Acknowledgements}\n" + PAPER_ACK_TEXT              + "\n"
        "\n\\section*{CRediT Authorship Contribution Statement}\n"
                                            + PAPER_CREDIT_TEXT          + "\n"
        "\n\\section*{Declaration of Competing Interest}\n"
                                            + PAPER_DECLARATION_TEXT     + "\n"
        "\n\\section*{Data Availability}\n" + PAPER_DATA_AVAILABILITY_TEXT + "\n"
    )

    tex = (
        _build_preamble()
            .replace("%ABSTRACT%", abstract_tex or r"\noindent[ABSTRACT PENDING]")
        + "\n\n".join(body_parts_final)
        + fixed_tail
        + prov_appendix
        + _POSTAMBLE
    )

    # Translate writer-style cite keys (RN<folder> / <folder-num> / 1-s2.0-*)
    # into the canonical BibTeX citekeys from PDFs.bib, then drop any key that
    # cannot be resolved. The writer is told to use [RNxxx] tags whose <xxx>
    # is an output_images/ folder name; PDFs.bib carries the real Zotero
    # citekeys (e.g. ``roux_current_1994``) along with ``file = {…:files/<NUM>/…}``.
    from corpus import _ocr_keys as _get_ocr_keys, folder_to_bibkey as _f2k
    folder_map = _f2k()                     # "1790" -> "roux_current_1994"
    ocr_folders = _get_ocr_keys()           # folder names on disk
    bib_keys = set(bib)

    def _resolve(k: str) -> str | None:
        k = k.strip()
        if not k:
            return None
        if k in bib_keys:
            return k
        # RN-prefixed folder id
        if k.startswith("RN") and k[2:].isdigit() and k[2:] in folder_map:
            return folder_map[k[2:]]
        # bare numeric folder id
        if k.isdigit() and k in folder_map:
            return folder_map[k]
        # 1-s2.0-* keys are kept as-is (no Zotero entry, OCR-only)
        if k.startswith("1-s2.0-") and k in ocr_folders:
            return k
        # last-resort: numeric folder OCR'd but missing in bib map -> keep raw
        if k in ocr_folders:
            return k
        return None

    def _filter_cite(m: re.Match) -> str:
        # Preserve \cite vs \citep vs \citet from the matched command
        cmd_match = re.match(r"\\cite([pt])?", m.group(0))
        suffix = cmd_match.group(1) or "" if cmd_match else ""
        cmd = r"\cite" + suffix
        kept: list[str] = []
        for raw in m.group(1).split(","):
            r = _resolve(raw)
            if r and r not in kept:
                kept.append(r)
        return cmd + "{" + ",".join(kept) + "}" if kept else ""

    before = len(re.findall(r"\\cite[pt]?\{", tex))
    tex    = re.sub(r"\\cite[pt]?\{([^}]+)\}", _filter_cite, tex)
    after  = len(re.findall(r"\\cite[pt]?\{", tex))
    if before != after:
        print(f"[render] stripped {before - after} unresolved \\citep{{}} from body")

    ELSEVIER_TEX.write_text(tex, encoding="utf-8")

    # Collect all cited keys (now guaranteed resolvable) and write references.bib
    used = set(re.findall(r"\\cite[pt]?\{([^}]+)\}", tex))
    used = {k.strip() for grp in used for k in grp.split(",") if k.strip()}
    # keep both bib citekeys and 1-s2.0-* OCR keys
    used &= (bib_keys | {k for k in ocr_folders if k.startswith("1-s2.0-")} | ocr_folders)
    bib_path = OUTPUT_DIR / "references.bib"
    bib_path.write_text(build_references_bib(used, bib), encoding="utf-8")

    print(f"\n[render] -> {ELSEVIER_TEX}")
    print(f"[render] -> {bib_path}  ({len(used)} citations)")
    print("\nCompile with:")
    print(f"  cd {OUTPUT_DIR} && pdflatex paper && bibtex paper && pdflatex paper && pdflatex paper")


if __name__ == "__main__":
    main()
