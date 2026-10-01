"""Render the assembled paper as an Elsevier (elsarticle) LaTeX document.

Consumes ``output/draft_sections.json`` (produced by pipeline._assemble) plus
the hypothesis/keywords inputs and emits:

    output/paper.tex          elsarticle-class manuscript
    output/elsarticle.cls     the document class (copied so it compiles anywhere)
    output/paper.pdf          compiled PDF (only if a LaTeX toolchain is present)

SVG figures are converted to PDF (via cairosvg) so pdflatex can embed them.
No .bib file is required — references are emitted as a manual thebibliography
built from the corpus citekeys actually cited in the draft.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import config

TEMPLATES = Path(__file__).resolve().parent / "templates"

# ── LaTeX escaping / markdown conversion ─────────────────────────────────────
_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def _escape(text: str) -> str:
    return "".join(_LATEX_SPECIALS.get(c, c) for c in text)


def _md_inline_to_latex(text: str, cite_keys: set[str]) -> str:
    """Convert a single markdown line's inline markup to LaTeX.

    Order: protect math + citations → escape → restore → bold/italic.
    """
    math_spans: list[str] = []

    def _stash_math(m: re.Match) -> str:
        math_spans.append(m.group(0))
        return f"\x00M{len(math_spans) - 1}\x00"

    text = re.sub(r"\$[^$]+\$", _stash_math, text)

    cites: list[str] = []

    def _stash_cite(m: re.Match) -> str:
        key = m.group(1).strip()
        if key in cite_keys:
            cites.append(key)
            return f"\x00C{len(cites) - 1}\x00"
        return m.group(0)

    text = re.sub(r"\[([^\]]+)\]", _stash_cite, text)

    text = _escape(text)

    # bold / italic (operate on escaped text; markers survive escaping)
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\\emph{\1}", text)

    for i, key in enumerate(cites):
        text = text.replace(f"\x00C{i}\x00", f"\\cite{{{key}}}")
    for i, span in enumerate(math_spans):
        text = text.replace(f"\x00M{i}\x00", span)
    return text


def _md_body_to_latex(body: str, cite_keys: set[str]) -> str:
    """Convert a section body (markdown paragraphs + bullet lists) to LaTeX."""
    out: list[str] = []
    in_list = False
    for raw in body.splitlines():
        line = raw.rstrip()
        if re.match(r"^\s*[-*]\s+", line):
            if not in_list:
                out.append(r"\begin{itemize}")
                in_list = True
            item = re.sub(r"^\s*[-*]\s+", "", line)
            out.append(r"  \item " + _md_inline_to_latex(item, cite_keys))
            continue
        if in_list:
            out.append(r"\end{itemize}")
            in_list = False
        if line.strip().startswith("#"):  # stray heading inside body
            line = line.lstrip("#").strip()
        out.append(_md_inline_to_latex(line, cite_keys) if line.strip() else "")
    if in_list:
        out.append(r"\end{itemize}")
    return "\n".join(out)


# ── Figures ──────────────────────────────────────────────────────────────────
def _svg_to_pdf(svg_path: Path) -> Path | None:
    """Convert an SVG to PDF next to it so pdflatex can embed it."""
    pdf_path = svg_path.with_suffix(".pdf")
    if pdf_path.exists():
        return pdf_path
    try:
        import cairosvg
        cairosvg.svg2pdf(url=str(svg_path), write_to=str(pdf_path))
        return pdf_path
    except Exception as e:
        print(f"  [render] SVG→PDF failed for {svg_path.name}: {e}")
        return None


def _figure_block(fig_path: str, caption: str, label: str) -> str | None:
    p = Path(fig_path)
    if p.suffix.lower() == ".svg":
        conv = _svg_to_pdf(p)
        if conv is None:
            return None
        p = conv
    rel = f"{config.FIGURES_DIR.name}/{p.name}"
    return (
        "\\begin{figure}[htbp]\n  \\centering\n"
        f"  \\includegraphics[width=0.8\\linewidth]{{{rel}}}\n"
        f"  \\caption{{{_escape(caption)}}}\n"
        f"  \\label{{fig:{label}}}\n"
        "\\end{figure}"
    )


# ── Document assembly ────────────────────────────────────────────────────────
_LEVEL_CMD = {0: "section", 1: "subsection", 2: "subsubsection", 3: "paragraph"}


def _preamble(title: str, keywords: list[str], abstract: str, journal: str) -> str:
    kw = " \\sep ".join(_escape(k) for k in keywords)
    return (
        "\\documentclass[preprint,12pt]{elsarticle}\n"
        "\\usepackage[utf8]{inputenc}\n"
        "\\usepackage{graphicx}\n"
        "\\usepackage{amsmath,amssymb}\n"
        "\\usepackage{hyperref}\n"
        "\\journal{" + _escape(journal) + "}\n\n"
        "\\begin{document}\n\n"
        "\\begin{frontmatter}\n\n"
        f"\\title{{{_escape(title)}}}\n\n"
        "\\author{Automated Literature Pipeline}\n\n"
        "\\begin{abstract}\n" + _md_inline_to_latex(abstract, set()) + "\n\\end{abstract}\n\n"
        f"\\begin{{keyword}}\n{kw}\n\\end{{keyword}}\n\n"
        "\\end{frontmatter}\n"
    )


def _abstract_from(hypothesis: dict, sections: list[dict]) -> str:
    base = hypothesis.get("abstract") or hypothesis.get("hypothesis") or ""
    rqs = hypothesis.get("research_questions") or []
    if rqs:
        base = base + " This review addresses: " + "; ".join(rqs)
    return base.strip()


def render() -> Path:
    sections = json.loads(config.DRAFT_JSON.read_text(encoding="utf-8"))
    hypothesis = json.loads(config.HYPOTHESIS_JSON.read_text(encoding="utf-8")) \
        if config.HYPOTHESIS_JSON.exists() else {}
    keywords = []
    if config.KEYWORDS_JSON.exists():
        kd = json.loads(config.KEYWORDS_JSON.read_text(encoding="utf-8"))
        keywords = kd.get("keywords", kd) if isinstance(kd, dict) else kd

    title = hypothesis.get("title") or "Automated Scientific Review"
    journal = hypothesis.get("journal") or "Preprint"
    cite_keys = {ck for s in sections for ck in s.get("citekeys", [])}

    parts: list[str] = [_preamble(title, keywords,
                                  _abstract_from(hypothesis, sections), journal)]

    for s in sections:
        lvl = _LEVEL_CMD.get(min(int(s.get("depth", 1)) - 1, 3), "subsection")
        parts.append(f"\n\\{lvl}{{{_escape(s['title'])}}}")
        parts.append(_md_body_to_latex(s.get("body", ""), cite_keys))
        for j, fig in enumerate(s.get("figures", [])):
            block = _figure_block(fig, s["title"], f"{s['id']}_{j}")
            if block:
                parts.append(block)

    # References — manual thebibliography (no .bib needed)
    used = sorted(cite_keys)
    if used:
        parts.append("\n\\begin{thebibliography}{" + str(len(used)) + "}")
        # short_ref needs a corpus; rebuild a light bib map from draft titles.
        from corpus import load_corpus
        corpus = load_corpus()
        for ck in used:
            parts.append(f"\\bibitem{{{ck}}} {_escape(corpus.short_ref(ck))}")
        parts.append("\\end{thebibliography}")

    parts.append("\n\\end{document}\n")

    config.PAPER_TEX.write_text("\n".join(parts), encoding="utf-8")
    # Ship the class file alongside the .tex so it compiles anywhere.
    cls = TEMPLATES / "elsarticle.cls"
    if cls.exists():
        shutil.copy(cls, config.OUTPUT_DIR / "elsarticle.cls")
    print(f"  [render] wrote {config.PAPER_TEX}")
    _compile()
    return config.PAPER_TEX


def _compile() -> None:
    """Compile paper.tex → paper.pdf if a LaTeX toolchain is available."""
    tool = shutil.which("latexmk") or shutil.which("pdflatex")
    if not tool:
        print("  [render] no LaTeX toolchain found — wrote paper.tex only "
              "(install texlive or compile on the host).")
        return
    cmd = ([tool, "-pdf", "-interaction=nonstopmode", config.PAPER_TEX.name]
           if tool.endswith("latexmk")
           else [tool, "-interaction=nonstopmode", config.PAPER_TEX.name])
    try:
        for _ in range(2 if tool.endswith("pdflatex") else 1):
            subprocess.run(cmd, cwd=config.OUTPUT_DIR, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if config.PAPER_PDF.exists():
            print(f"  [render] compiled {config.PAPER_PDF}")
    except Exception as e:
        print(f"  [render] LaTeX compile failed: {e}")


if __name__ == "__main__":
    render()
