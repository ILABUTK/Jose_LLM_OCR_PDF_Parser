"""07 — LLM-assisted SVG figure generation.

For each section in draft_sections.json, asks qwen3-coder-next:latest to
write a self-contained matplotlib script that produces an SVG figure
from data explicitly present in the section text and evidence bank.

Rules enforced in the prompt:
  - Use ONLY data values that appear verbatim in the evidence (no invention)
  - If data is insufficient, the script must raise SystemExit("NO_DATA")
  - Output must save to the path passed as sys.argv[1]
  - No network calls, no file reads beyond stdlib

Generated SVG files are written to output/figures/ and back-referenced in
draft_sections.json under a new "generated_figures" key.

Usage:
    python 07_generate_figures.py
    python 07_generate_figures.py --section sec_004   # single section
"""
from __future__ import annotations
import ast
import json
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from config import (
    CODER_MODEL,
    DRAFT_SECTIONS,
    OUTPUT_DIR,
)
from ollama_client import chat

FIG_DIR = OUTPUT_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

MAX_CODE_RETRIES = 3

# Roles that never get generated figures
SKIP_ROLES = {"abstract", "backmatter", "frontmatter"}
SKIP_TITLES = {
    "highlights", "funding", "acknowledgements",
    "credit authorship contribution statement",
    "declaration of competing interest", "data availability",
}

# ── Prompts ───────────────────────────────────────────────────────────────────
_SYS = """You are a scientific Python coder.
Write a self-contained matplotlib script that generates ONE publication-quality
SVG figure for the given section.

STRICT RULES:
0. Your script MUST begin with these exact lines (required for headless servers):
       import sys
       import matplotlib
       matplotlib.use('Agg')
       import matplotlib.pyplot as plt
   Do NOT import matplotlib.pyplot before calling matplotlib.use('Agg').
1. Use ONLY numerical values, labels, and data that appear VERBATIM in the
   SECTION TEXT or EVIDENCE provided. Do NOT invent or interpolate values.
2. If the provided text does not contain enough concrete data to draw a
   meaningful figure, output ONLY these two lines:
       import sys
       raise SystemExit("NO_DATA")
3. The script must save the figure to the path in sys.argv[1] using:
       plt.savefig(sys.argv[1], format="svg", bbox_inches="tight", dpi=150)
       plt.close('all')
4. Use plt.rcParams for font sizes: axes.titlesize=12, axes.labelsize=11
5. No network calls. No file reads. No hardcoded paths.
6. The script must be runnable as: python script.py /path/output.svg
7. Output ONLY the Python code — no markdown fences, no explanation."""

_USER = """Section title: {title}

Section text (extract data from here — do NOT invent):
---
{text}
---

Evidence bank (additional data — cite the source in the figure legend/title):
---
{evidence}
---

Write the matplotlib script now."""


# ── Helpers ───────────────────────────────────────────────────────────────────
def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _strip_fences(code: str) -> str:
    code = re.sub(r"^```(?:python)?\s*", "", code.strip())
    code = re.sub(r"\s*```$", "", code.strip())
    return code.strip()


def _is_valid_python(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def _run_script(code: str, out_path: Path) -> tuple[bool, str]:
    """Write code to a temp file and execute it. Returns (success, stderr)."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w",
                                    delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp = Path(f.name)
    try:
        result = subprocess.run(
            [sys.executable, str(tmp), str(out_path)],
            capture_output=True, text=True, timeout=60,
        )
        return result.returncode == 0, (result.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    finally:
        tmp.unlink(missing_ok=True)


def _extract_evidence(section: dict) -> str:
    """Pull evidence text stored in the section (if any) else empty string."""
    # draft_sections stores figures_available which includes evidence context
    fig_bank = section.get("figures_available", "")
    # Also grab a short excerpt of the final text itself as evidence
    return fig_bank[:2000] if fig_bank else ""


def generate_for_section(section: dict) -> list[str]:
    """Ask the LLM to generate an SVG for this section. Returns list of saved paths."""
    title = section["title"]
    tl    = title.lower().strip()
    role  = section.get("role", "")

    if role in SKIP_ROLES or tl in SKIP_TITLES:
        return []

    final_text = _strip_think(section.get("final", ""))
    if len(final_text) < 100:
        return []

    evidence = _extract_evidence(section)

    msg = [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": _USER.format(
            title=title,
            text=final_text[:3000],
            evidence=evidence[:1500],
        )},
    ]

    saved: list[str] = []
    last_error = ""

    for attempt in range(MAX_CODE_RETRIES):
        raw = chat(CODER_MODEL, msg, temperature=0.1, num_predict=2048)
        code = _strip_fences(_strip_think(raw))

        # Model decided no data — skip silently
        if 'SystemExit("NO_DATA")' in code or "NO_DATA" in code[:60]:
            print(f"  [fig] no data for '{title}' — skipped")
            return []

        if not _is_valid_python(code):
            last_error = "SyntaxError in generated code"
            print(f"  [fig] attempt {attempt+1}: syntax error, retrying…")
            msg.append({"role": "assistant", "content": raw})
            msg.append({"role": "user", "content":
                f"The code has a syntax error. Fix it. Output ONLY valid Python."})
            continue

        safe_title = re.sub(r"[^\w]", "_", title)[:40]
        out_path = FIG_DIR / f"{section['id']}_{safe_title}.svg"

        ok, stderr = _run_script(code, out_path)
        if ok and out_path.exists():
            print(f"  [fig] saved {out_path.name}")
            saved.append(str(out_path))
            break
        else:
            last_error = stderr[:300] if stderr else "unknown error"
            print(f"  [fig] attempt {attempt+1} runtime error: {last_error[:80]}")
            msg.append({"role": "assistant", "content": raw})
            msg.append({"role": "user", "content":
                f"The script failed with:\n{last_error}\n\n"
                f"Fix all errors. Remember sys.argv[1] is the output path. "
                f"Output ONLY the corrected Python code."})

    if not saved:
        print(f"  [fig] FAILED after {MAX_CODE_RETRIES} attempts: '{title}' — {last_error[:80]}")

    return saved


def main() -> None:
    # Optional: --section sec_xxx to run a single section
    target_id: str | None = None
    if "--section" in sys.argv:
        idx = sys.argv.index("--section")
        target_id = sys.argv[idx + 1]

    sections: list[dict] = json.loads(DRAFT_SECTIONS.read_text())
    updated = False

    for s in sections:
        if target_id and s["id"] != target_id:
            continue
        print(f"[fig {s['id']}] {s['title']}")
        paths = generate_for_section(s)
        if paths:
            s.setdefault("generated_figures", [])
            s["generated_figures"] = list(set(s["generated_figures"] + paths))
            updated = True

    if updated:
        DRAFT_SECTIONS.write_text(json.dumps(sections, indent=2, ensure_ascii=False))
        print(f"\n[fig] Updated {DRAFT_SECTIONS}")
    else:
        print("\n[fig] No new figures generated.")


if __name__ == "__main__":
    main()
