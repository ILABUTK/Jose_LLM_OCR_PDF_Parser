"""Render figures + a LaTeX side-by-side table from alignment_report.json.

Outputs:
  slides/newfigures/alignment_per_section.png   — per-section alignment bar chart
  slides/newfigures/alignment_table.tex         — LaTeX rows (best 3 + worst 1)
"""
import json, re, textwrap
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

REPORT = Path(__file__).resolve().parents[1] / "paper_generation/output/alignment_report.json"
OUT_DIR = Path(__file__).parent / "newfigures"
PNG = OUT_DIR / "alignment_per_section.png"
TEX = OUT_DIR / "alignment_table.tex"

# ── Helpers ──────────────────────────────────────────────────────────────────
def shorten(t: str, n: int = 38) -> str:
    t = re.sub(r"^\d+(?:\.\d+)*\.\s*", "", t)
    return (t[: n - 1] + "…") if len(t) > n else t


_UNICODE = {
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
    "⁻": "-", "⁺": "+", "≈": r"$\approx$", "≥": r"$\geq$", "≤": r"$\leq$",
    "—": "---", "–": "--", "“": "``", "”": "''", "’": "'",
    "→": r"$\to$",
}


def _escape_text(s: str) -> str:
    """Escape LaTeX special chars in NON-math text only."""
    repl = [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
            ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}"),
            ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"),
            ("<", r"\textless{}"), (">", r"\textgreater{}")]
    for a, b in repl:
        s = s.replace(a, b)
    for u, v in _UNICODE.items():
        s = s.replace(u, v)
    return s


def tex_escape(s: str) -> str:
    """Strip cites + escape LaTeX, but leave $...$ math segments untouched."""
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL)
    s = re.sub(r"\\cite\{[^}]+\}", "", s)
    s = re.sub(r"\[(RN\d+|1-s2\.0-[^\]]+)\]", "", s)
    parts = re.split(r"(\$[^$]+\$)", s)
    return "".join(p if (p.startswith("$") and p.endswith("$"))
                   else _escape_text(p)
                   for p in parts).strip()


def trim(s: str, n: int = 140) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


# ── Per-section bar chart ────────────────────────────────────────────────────
_BOILERPLATE = ("funding", "acknowledg", "credit", "competing",
                "data availability", "declaration", "conflict")


def _is_boilerplate(title: str) -> bool:
    t = title.lower()
    return any(t.startswith(k) or k in t for k in _BOILERPLATE)


def make_chart(report: dict):
    secs = {k: v for k, v in report["per_section"].items()
            if not _is_boilerplate(v["title"])}
    labels = [shorten(v["title"]) for v in secs.values()]
    means  = [v["mean"] for v in secs.values()]
    ns     = [v["n"]    for v in secs.values()]
    y = np.arange(len(labels))

    colors = ["#16A085" if m >= 0.80
              else "#3CB878" if m >= 0.75
              else "#E8A020" if m >= 0.65
              else "#E84040" for m in means]

    fig, ax = plt.subplots(figsize=(13, 7), dpi=160)
    bars = ax.barh(y, means, color=colors, edgecolor="#222", linewidth=0.6,
                   height=0.72)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=11)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.0)
    ax.axvline(report["overall_mean"], color="#1d1d1f",
               ls="--", lw=1.4, alpha=0.7,
               label=f"overall mean = {report['overall_mean']:.3f}")
    ax.set_xlabel("Per-section alignment score  (cosine sim, best human match)",
                  fontsize=12)
    ax.legend(loc="lower right", fontsize=11, frameon=False)
    ax.grid(axis="x", lw=0.4, alpha=0.5)
    for b, m, n in zip(bars, means, ns):
        ax.text(m + 0.01, b.get_y() + b.get_height() / 2,
                f"{m:.2f}  (n={n})", va="center", fontsize=9.5, color="#333")
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    OUT_DIR.mkdir(exist_ok=True)
    plt.savefig(PNG, bbox_inches="tight", facecolor="white")
    print(f"wrote {PNG}")


# ── LaTeX rows (real claims, best 3 + worst 1) ───────────────────────────────
def make_table(report: dict):
    pairs = sorted(report["pairs"], key=lambda p: p["final"], reverse=True)
    # filter for sentences with a digit and a meaningful section
    informative = [p for p in pairs
                   if re.search(r"\d", p["gen"])
                   and not _is_boilerplate(p["section_title"])]
    top3   = informative[:3]
    worst  = informative[-1] if informative else None

    rows = top3 + ([worst] if worst else [])
    lines = []
    for p in rows:
        gen   = tex_escape(trim(p["gen"],   135))
        human = tex_escape(trim(p["human"], 125))
        s     = p["final"]
        color = ("ornlgreen" if s >= 0.78
                 else "backgroundgreen" if s >= 0.70 else "cerulean")
        sec   = tex_escape(shorten(p["section_title"], 22))
        verdict = (r"\textbf{pass}" if s >= 0.70 else r"\textbf{flag}")
        lines.append(
            f"\\textcolor{{{color}}}{{{gen}}}\n"
            f"& {human}\n"
            f"& \\textcolor{{{color}}}{{{s:.2f}}}\n"
            f"& {{\\scriptsize {sec}}}\\newline {verdict} \\\\\n"
            r"\addlinespace[2pt]"
        )
    body = "\n".join(lines)
    TEX.write_text(body, encoding="utf-8")
    print(f"wrote {TEX}  ({len(rows)} rows, overall mean = {report['overall_mean']:.3f})")


def main():
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    print(f"[load] {report['n_pairs']} pairs, "
          f"overall mean = {report['overall_mean']:.3f}, "
          f"LLM-verified={report['llm_verified']}")
    make_chart(report)
    make_table(report)


if __name__ == "__main__":
    main()
