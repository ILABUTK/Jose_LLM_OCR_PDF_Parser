"""LLM-driven SVG figure generator — the ComfyUI replacement.

Instead of a GPU diffusion service, figures are produced by asking the LLM to
emit a standalone, publication-quality **SVG** schematic/plot grounded in a
reasoning node's claim and its retrieved corpus evidence. This removes the
heavy ComfyUI container entirely and yields vector figures that embed cleanly
in Markdown/LaTeX.

Public API mirrors the old comfy_client so the rest of the pipeline is
unchanged:
    health()                                   -> bool  (always True)
    generate_for_node(node_id, prompt, evidence) -> list[str]  (saved .svg paths)
"""
from __future__ import annotations

import re

import config
from llm_client import complete

_SVG_SYS = (
    "You are a scientific figure illustrator. Produce ONE standalone, valid SVG "
    "document (publication quality) that visually explains the requested idea: "
    "a labelled schematic, diagram, or plot. Requirements:\n"
    "  - Output ONLY the SVG, starting with <svg and ending with </svg>.\n"
    "  - Include an explicit width, height and viewBox.\n"
    "  - Use readable labels, a title, axis/legend text where relevant.\n"
    "  - Ground every quantitative value in the supplied EVIDENCE; never invent "
    "numbers that contradict it. If no data is given, draw a conceptual "
    "schematic rather than a quantitative plot.\n"
    "  - No external images, scripts, or <foreignObject>; pure SVG shapes/text."
)

_SVG_RE = re.compile(r"<svg\b.*?</svg>", re.DOTALL | re.IGNORECASE)


def health() -> bool:
    """Always available — generation runs through the LLM, no GPU service."""
    return True


def _extract_svg(raw: str) -> str | None:
    raw = re.sub(r"```(?:svg|xml|html)?", "", raw)
    m = _SVG_RE.search(raw)
    return m.group(0).strip() if m else None


def generate_for_node(
    node_id: str,
    prompt: str,
    evidence: str | None = None,
    count: int = 1,
) -> list[str]:
    """Generate `count` SVG figures for one node. Returns saved paths."""
    saved: list[str] = []
    for i in range(count):
        user = (
            f"FIGURE BRIEF:\n{prompt}\n\n"
            f"EVIDENCE (ground all values in this):\n{evidence or '(none provided)'}\n\n"
            f"Draw variation #{i + 1}. Return ONLY the SVG."
        )
        raw = complete(_SVG_SYS, user, temperature=0.3,
                       max_tokens=config.SVG_MAX_TOKENS)
        svg = _extract_svg(raw)
        if not svg:
            raise RuntimeError(f"no valid <svg> returned for {node_id} #{i}")
        dst = config.FIGURES_DIR / f"{node_id}_fig{i}.svg"
        dst.write_text(svg, encoding="utf-8")
        saved.append(str(dst))
        print(f"  [svg] saved {dst.name}")
    return saved
