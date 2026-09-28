#!/usr/bin/env bash
# ============================================================
#  Full paper-generation pipeline
#
#  Stage order:
#    1 → extract ontologies
#    2 → plan outline
#    3 → agents write  (writer ↔ critic ↔ judge)
#    4 → validate
#    7 → SVG figure generation  (LLM coder → matplotlib → SVG)
#    5 → render LaTeX            (needs draft_sections.json + figures)
#    6 → LLM LaTeX fixer + pdflatex compile loop
#
#  Usage:
#    ./run_pipeline.sh              # run all stages in order
#    ./run_pipeline.sh --from 5     # re-render + compile only
#    ./run_pipeline.sh --only 7     # regenerate figures only
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/../venv"
PYTHON="$VENV/bin/python"
LOG="$SCRIPT_DIR/pipeline_$(date +%Y%m%d_%H%M%S).log"

# ── Parse arguments ──────────────────────────────────────────
FROM_STAGE=1
ONLY_STAGE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from) FROM_STAGE="$2"; shift 2 ;;
        --only) ONLY_STAGE="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────
log()  { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
die()  { log "ERROR: $*"; exit 1; }

should_run() {
    local stage="$1"
    [[ -n "$ONLY_STAGE" ]] && [[ "$stage" == "$ONLY_STAGE" ]] && return 0
    [[ -n "$ONLY_STAGE" ]] && return 1
    [[ "$stage" -ge "$FROM_STAGE" ]] && return 0
    return 1
}

cd "$SCRIPT_DIR"

# ── Validate Python / venv ────────────────────────────────────
[[ -x "$PYTHON" ]] || die "venv not found at $VENV — run: python -m venv $VENV && pip install -r requirements.txt"

log "Pipeline started  (from=$FROM_STAGE${ONLY_STAGE:+, only=$ONLY_STAGE})"
log "Log: $LOG"

# ── Stage 1: Extract ontologies ──────────────────────────────
if should_run 1; then
    log "=== Stage 1: extract ontologies ==="
    "$PYTHON" 01_extract_ontologies.py 2>&1 | tee -a "$LOG"
fi

# ── Stage 2: Plan outline ────────────────────────────────────
if should_run 2; then
    log "=== Stage 2: plan outline ==="
    "$PYTHON" 02_plan_paper.py 2>&1 | tee -a "$LOG"
fi

# ── Stage 3: Agents write (writer ↔ critic ↔ judge loop) ────
if should_run 3; then
    log "=== Stage 3: agents write ==="
    "$PYTHON" 03_agents_write.py 2>&1 | tee -a "$LOG"
fi

# ── Stage 4: Validate ────────────────────────────────────────
if should_run 4; then
    log "=== Stage 4: validate ==="
    "$PYTHON" 04_validate.py 2>&1 | tee -a "$LOG" || {
        log "WARNING: validation returned non-zero — continuing"
    }
fi

# ── Stage 7: SVG figure generation (LLM coder → matplotlib → SVG) ─────────
if should_run 7; then
    log "=== Stage 7: SVG figure generation ==="
    "$PYTHON" 07_generate_figures.py 2>&1 | tee -a "$LOG" || {
        log "WARNING: figure generation had errors — continuing without some figures"
    }
fi

# ── Stage 5: Render LaTeX ────────────────────────────────────
if should_run 5; then
    log "=== Stage 5: render LaTeX ==="
    "$PYTHON" 05_render_elsevier.py 2>&1 | tee -a "$LOG"
fi

# ── Stage 6: LLM LaTeX fixer + compile loop ──────────────────
if should_run 6; then
    log "=== Stage 6: LLM LaTeX fixer + compile ==="
    "$PYTHON" 06_fix_latex.py 2>&1 | tee -a "$LOG"
    FIX_RC=$?
    if [[ $FIX_RC -eq 0 ]]; then
        log "LaTeX compiled cleanly."
    elif [[ $FIX_RC -eq 1 ]]; then
        log "WARNING: LaTeX errors remain after fix rounds — check output/paper.log"
    else
        die "06_fix_latex.py failed (exit $FIX_RC)"
    fi
fi
log "Pipeline complete."
log "Output files:"
ls -lh "$SCRIPT_DIR/output/paper."* 2>/dev/null | tee -a "$LOG" || true
