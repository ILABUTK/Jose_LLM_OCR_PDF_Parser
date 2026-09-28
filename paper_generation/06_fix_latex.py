"""06 — LLM-assisted LaTeX error fixer (coder loop).

Reads pdflatex/bibtex log files, extracts errors, asks qwen3-coder:30b to
patch paper.tex, then re-compiles.  Repeats up to MAX_FIX_ROUNDS times.

Usage:
    python 06_fix_latex.py

Exit codes:
    0 — compiled cleanly (no errors)
    1 — errors remain after MAX_FIX_ROUNDS
    2 — paper.tex not found (run 05_render_elsevier.py first)
"""
from __future__ import annotations
import re
import subprocess
import sys
import textwrap
from pathlib import Path

from config import CODER_MODEL, ELSEVIER_TEX, OUTPUT_DIR
from ollama_client import chat

MAX_FIX_ROUNDS = 6
LOG_CONTEXT_LINES = 8   # lines above/below an error line in .tex to give the model

# ── LaTeX error extraction ────────────────────────────────────────────────────

_ERROR_RE = re.compile(
    r"^(?:!"                            # pdflatex fatal
    r"|.*?:\d+: )"                      # file:line: errors
    r".+",
    re.MULTILINE,
)

_LINE_RE = re.compile(r"^l\.(\d+)\s", re.MULTILINE)

_BIBTEX_WARN_RE = re.compile(
    r"^(Warning|Error)--.*$",
    re.MULTILINE,
)


def _read_log(log_path: Path) -> str:
    try:
        return log_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def extract_latex_errors(log: str) -> list[str]:
    """Return unique error lines from a pdflatex log."""
    errors: list[str] = []
    for m in _ERROR_RE.finditer(log):
        line = m.group(0).strip()
        if line and line not in errors:
            errors.append(line)
    return errors[:40]   # cap at 40 to fit context


def extract_bibtex_warnings(log: str) -> list[str]:
    warnings: list[str] = []
    for m in _BIBTEX_WARN_RE.finditer(log):
        w = m.group(0).strip()
        if w and w not in warnings:
            warnings.append(w)
    return warnings[:20]


def has_fatal_errors(log: str) -> bool:
    """True if pdflatex produced fatal (!) errors."""
    return bool(re.search(r"^!", log, re.MULTILINE))


def has_undefined_refs(log: str) -> bool:
    return "undefined" in log.lower() or "Citation" in log


def _error_context(tex: str, errors: list[str]) -> str:
    """Extract snippets of tex around reported error line numbers."""
    lines = tex.splitlines()
    snippets: list[str] = []
    seen_lnums: set[int] = set()
    for err in errors:
        m = _LINE_RE.search(err)
        if m:
            lnum = int(m.group(1)) - 1   # 0-indexed
            if lnum in seen_lnums:
                continue
            seen_lnums.add(lnum)
            start = max(0, lnum - LOG_CONTEXT_LINES)
            end   = min(len(lines), lnum + LOG_CONTEXT_LINES + 1)
            block = "\n".join(
                f"{i+1:4d}| {l}" for i, l in enumerate(lines[start:end], start=start)
            )
            snippets.append(f"[Around line {lnum+1}]\n{block}")
    return "\n\n".join(snippets)


# ── LLM fixer ────────────────────────────────────────────────────────────────

_SYSTEM = """You are an expert LaTeX editor specialising in Elsevier elsarticle documents.

TASK: Fix ONLY the LaTeX compilation errors listed below. Return the COMPLETE
corrected paper.tex — no truncation, no omissions, no placeholders.

STRICT RULES:
1. Do NOT add, invent, or modify any scientific content, numerical values,
   citations, or references that did not already appear in the source file.
   Only fix LaTeX syntax/structure issues.
2. Do NOT remove or replace real citations (\\cite{...}).  If a citation key
   looks wrong, leave it as-is or correct the LaTeX syntax only.
3. Do NOT hallucinate new \\cite{} keys.  Use only keys that are already
   present in the source.
4. Fix unbalanced braces, bad table structures, illegal characters,
   undefined commands, and similar LaTeX issues.
5. Ensure every \\begin{...} has a matching \\end{...}.
6. Output ONLY the corrected .tex file content — no markdown fences, no
   explanation, no think blocks.
7. NEVER change the \\documentclass line. The document MUST remain
   \\documentclass[review,12pt,a4paper]{elsarticle} — do not simplify it to
   plain \\article or any other class.
8. NEVER remove \\usepackage{natbib} or \\bibliographystyle{elsarticle-num}."""

_USER_TMPL = """=== ERRORS FROM PDFLATEX LOG ===
{errors}

=== WARNINGS FROM BIBTEX LOG ===
{bibtex_warnings}

=== RELEVANT TEX CONTEXT (from paper.tex) ===
{context}

=== FULL paper.tex ===
{tex}

Return the COMPLETE corrected paper.tex now."""


def ask_coder_to_fix(tex: str, errors: list[str], bibtex_warnings: list[str]) -> str:
    context = _error_context(tex, errors)
    errors_str   = "\n".join(errors)         if errors          else "(none)"
    warnings_str = "\n".join(bibtex_warnings) if bibtex_warnings else "(none)"

    user_msg = _USER_TMPL.format(
        errors=errors_str,
        bibtex_warnings=warnings_str,
        context=context or "(no line-number context available)",
        tex=tex,
    )
    print(f"  [fixer] sending {len(user_msg):,} chars to {CODER_MODEL} …")
    result = chat(
        CODER_MODEL,
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.0,
        num_predict=8192,
    )
    # Strip any markdown fences the model may have added despite instructions
    result = re.sub(r"^```(?:latex|tex)?\s*\n?", "", result.strip())
    result = re.sub(r"\n?```\s*$",                "", result.strip())
    # Strip <think> blocks
    result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()
    return result


# ── Compile helpers ───────────────────────────────────────────────────────────

def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd,
        capture_output=True, text=True, timeout=300,
    )


def compile_latex(output_dir: Path) -> tuple[bool, str]:
    """Run pdflatex + bibtex + pdflatex×2.  Returns (success, log_text)."""
    r1 = _run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "paper"], output_dir)
    log = _read_log(output_dir / "paper.log")
    if has_fatal_errors(log):
        return False, log

    _run(["bibtex", "paper"], output_dir)
    bibtex_log = _read_log(output_dir / "paper.blg")

    _run(["pdflatex", "-interaction=nonstopmode", "paper"], output_dir)
    _run(["pdflatex", "-interaction=nonstopmode", "paper"], output_dir)

    log = _read_log(output_dir / "paper.log")
    return not has_fatal_errors(log), log


def _bibtex_log(output_dir: Path) -> str:
    return _read_log(output_dir / "paper.blg")


# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    tex_path = ELSEVIER_TEX
    if not tex_path.exists():
        print(f"[fix] ERROR: {tex_path} not found — run 05_render_elsevier.py first.")
        sys.exit(2)

    # Copy cls/bst if missing from output dir
    for asset in ("elsarticle.cls", "elsarticle-num.bst"):
        dst = OUTPUT_DIR / asset
        if not dst.exists():
            src = Path(__file__).parent / "elsarticle-2" / asset
            if src.exists():
                dst.write_bytes(src.read_bytes())
                print(f"[fix] copied {asset} to output/")

    print(f"[fix] Initial compile …")
    ok, log = compile_latex(OUTPUT_DIR)

    # If compile succeeded (PDF was produced), accept it even with undefined-citation
    # warnings — do NOT let the LLM rewrite a working document.
    if ok:
        und = has_undefined_refs(log)
        if und:
            print(f"[fix] ✓ PDF compiled; {sum(1 for _ in re.finditer(r'natbib Warning', log))} citation warning(s) remain — leaving body intact.")
        else:
            print(f"[fix] ✓ Compiled cleanly (no LLM fix needed).")
        sys.exit(0)

    for rnd in range(1, MAX_FIX_ROUNDS + 1):
        if ok and not has_undefined_refs(log):
            print(f"[fix] ✓ Compiled cleanly (round {rnd - 1})")
            sys.exit(0)

        errors          = extract_latex_errors(log)
        bibtex_warnings = extract_bibtex_warnings(_bibtex_log(OUTPUT_DIR))

        if not errors and not bibtex_warnings:
            print(f"[fix] ✓ No errors detected — done.")
            sys.exit(0)

        print(f"\n[fix] Round {rnd}/{MAX_FIX_ROUNDS} — {len(errors)} errors, "
              f"{len(bibtex_warnings)} bibtex warnings")
        for e in errors[:10]:
            print(f"  ! {e}")

        tex = tex_path.read_text(encoding="utf-8")
        fixed = ask_coder_to_fix(tex, errors, bibtex_warnings)

        if not fixed.strip():
            print("[fix] WARN: model returned empty response — keeping original")
            break

        # Sanity: fixed tex must contain \begin{document}
        if r"\begin{document}" not in fixed:
            print("[fix] WARN: model returned incomplete tex (missing \\begin{document}) — reverting")
            break

        # Sanity: must preserve elsarticle class (LLM must not downgrade to plain article)
        if "elsarticle" not in fixed:
            print("[fix] WARN: model removed elsarticle class — restoring original preamble")
            body_m = re.search(r"\\begin\{document\}(.*?)\\end\{document\}",
                               fixed, re.DOTALL)
            orig_preamble_end = tex.find(r"\begin{document}")
            if body_m and orig_preamble_end >= 0:
                orig_preamble = tex[:orig_preamble_end]
                fixed = orig_preamble + "\\begin{document}" + body_m.group(1) + "\\end{document}\n"
                print("[fix] Preamble restored from original; body taken from LLM output.")
            else:
                break  # revert entirely

        tex_path.write_text(fixed, encoding="utf-8")
        print(f"[fix] Wrote patched tex ({len(fixed):,} chars), recompiling …")
        new_ok, new_log = compile_latex(OUTPUT_DIR)

        # Regression guard: if the fix doesn't reduce the error count, revert.
        prev_errs = len(extract_latex_errors(log))
        new_errs  = len(extract_latex_errors(new_log))
        if not new_ok and new_errs >= prev_errs:
            print(f"[fix] WARN: fix did not reduce errors ({prev_errs} -> {new_errs}); reverting and stopping.")
            tex_path.write_text(tex, encoding="utf-8")
            compile_latex(OUTPUT_DIR)  # restore .pdf if previous compiled
            break
        ok, log = new_ok, new_log

    # Final check
    if ok and not has_undefined_refs(log):
        print(f"[fix] ✓ Compiled cleanly after {rnd} fix round(s).")
        sys.exit(0)
    else:
        remaining = extract_latex_errors(log)
        print(f"\n[fix] ✗ {len(remaining)} error(s) remain after {MAX_FIX_ROUNDS} rounds:")
        for e in remaining[:20]:
            print(f"  ! {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
