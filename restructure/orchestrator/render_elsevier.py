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
from llm_client import complete

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
def _svg_to_pdf(svg_path: Path) -> Path:
    """Convert an SVG to PDF next to it so pdflatex can embed it."""
    pdf_path = svg_path.with_suffix(".pdf")
    if pdf_path.exists():
        return pdf_path
    import cairosvg
    cairosvg.svg2pdf(url=str(svg_path), write_to=str(pdf_path))
    return pdf_path


def _figure_block(fig_path: str, caption: str, label: str) -> str:
    p = Path(fig_path)
    if p.suffix.lower() == ".svg":
        p = _svg_to_pdf(p)
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


_ABSTRACT_SYS = (
    "You are a scientific writer. Write a single-paragraph abstract (120-200 "
    "words) for a review article, imitating the author's STYLE GUIDE. Summarise "
    "the contribution, approach, and principal findings drawn from the SECTION "
    "DRAFTS. Do NOT include headings, citations, bullet points, or a list of "
    "research questions. Output only the abstract prose."
)


def _abstract_from(hypothesis: dict, sections: list[dict]) -> str:
    from style import style_summary
    body = "\n\n".join(f"## {s['title']}\n{s['body']}" for s in sections)
    user = (
        f"STYLE GUIDE:\n{style_summary()}\n\n"
        f"TITLE: {hypothesis['title']}\n"
        f"CENTRAL HYPOTHESIS: {hypothesis['hypothesis']}\n\n"
        f"SECTION DRAFTS:\n{body[:12000]}\n\n"
        "Write the abstract now."
    )
    return complete(_ABSTRACT_SYS, user, temperature=0.3, max_tokens=600).strip()


def render() -> Path:
    sections = json.loads(config.DRAFT_JSON.read_text(encoding="utf-8"))
    hypothesis = json.loads(config.HYPOTHESIS_JSON.read_text(encoding="utf-8"))
    kd = json.loads(config.KEYWORDS_JSON.read_text(encoding="utf-8"))
    keywords = kd["keywords"] if isinstance(kd, dict) else kd

    title = hypothesis["title"]
    journal = hypothesis["journal"]
    cite_keys = {ck for s in sections for ck in s["citekeys"]}

    parts: list[str] = [_preamble(title, keywords,
                                  _abstract_from(hypothesis, sections), journal)]

    for s in sections:
        lvl = _LEVEL_CMD.get(min(int(s["depth"]) - 1, 3), "subsection")
        parts.append(f"\n\\{lvl}{{{_escape(s['title'])}}}")
        parts.append(_md_body_to_latex(s["body"], cite_keys))
        for j, fig in enumerate(s["figures"]):
            block = _figure_block(fig, s["title"], f"{s['id']}_{j}")
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
    """Compile paper.tex → paper.pdf with the LaTeX toolchain."""
    tool = shutil.which("latexmk") or shutil.which("pdflatex")
    if not tool:
        raise RuntimeError("no LaTeX toolchain found (install latexmk or pdflatex)")
    cmd = ([tool, "-pdf", "-interaction=nonstopmode", config.PAPER_TEX.name]
           if tool.endswith("latexmk")
           else [tool, "-interaction=nonstopmode", config.PAPER_TEX.name])
    for _ in range(2 if tool.endswith("pdflatex") else 1):
        subprocess.run(cmd, cwd=config.OUTPUT_DIR, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not config.PAPER_PDF.exists():
        raise RuntimeError("LaTeX compile produced no PDF — inspect paper.log")
    print(f"  [render] compiled {config.PAPER_PDF}")


if __name__ == "__main__":
    render()
