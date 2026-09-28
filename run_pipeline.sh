#!/usr/bin/env bash
# =============================================================================
# run_pipeline.sh — Full paper-generation pipeline
#
# Stages:
#   01  Extract ontologies (structure + style) from reference paper
#   02  Plan outline (18 sections)
#   03  Agents write all sections  ← LLM-heavy, streaming qwen3:32b
#   04  Validate (semantic grounding, citation coverage, style alignment)
#   05  Render to Elsevier LaTeX
#   06  LLM-assisted LaTeX fix loop  (qwen3-coder:30b, up to 6 rounds)
#   07  Final PDF compile
#
# Usage:
#   ./run_pipeline.sh              # run all stages
#   ./run_pipeline.sh --from 05    # resume from stage 05 onwards
#   ./run_pipeline.sh --only 06    # run only one stage
#
# Progress is logged to: logs/pipeline_YYYYMMDD_HHMMSS.log
# =============================================================================

set -euo pipefail

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_DIR="$SCRIPT_DIR/paper_generation"
OUTPUT_DIR="$PIPELINE_DIR/output"
LOG_DIR="$PIPELINE_DIR/logs"
VENV="$SCRIPT_DIR/venv"
PYTHON="$VENV/bin/python"

mkdir -p "$LOG_DIR" "$OUTPUT_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOGFILE="$LOG_DIR/pipeline_${TIMESTAMP}.log"

# ── Argument parsing ──────────────────────────────────────────────────────────
FROM_STAGE=1
ONLY_STAGE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from) FROM_STAGE="$2"; shift 2 ;;
        --only) ONLY_STAGE="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Logging ───────────────────────────────────────────────────────────────────
exec > >(tee -a "$LOGFILE") 2>&1

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
ok()   { echo "[$(date '+%H:%M:%S')] ✓ $*"; }
fail() { echo "[$(date '+%H:%M:%S')] ✗ $*"; exit 1; }

log "=== Paper-generation pipeline start ==="
log "Log: $LOGFILE"
log "From stage: ${ONLY_STAGE:-${FROM_STAGE}}"

# ── Helpers ───────────────────────────────────────────────────────────────────
should_run() {
    local stage="$1"
    if [[ -n "$ONLY_STAGE" ]]; then
        [[ "$stage" == "$ONLY_STAGE" ]]
    else
        [[ "$stage" -ge "$FROM_STAGE" ]]
    fi
}

run_stage() {
    local num="$1"
    local script="$2"
    local desc="$3"

    if ! should_run "$num"; then
        log "[skip] Stage $num: $desc"
        return 0
    fi

    log "=== Stage $num: $desc ==="
    cd "$PIPELINE_DIR"
    "$PYTHON" "$script" || fail "Stage $num ($script) failed — see $LOGFILE"
    ok "Stage $num done"
}

# ── LaTeX compile helper ──────────────────────────────────────────────────────
compile_latex() {
    log "Compiling LaTeX (pdflatex + bibtex + 2× pdflatex) …"
    cd "$OUTPUT_DIR"

    # Copy class/bst files if not present
    for f in elsarticle.cls elsarticle-num.bst; do
        [[ -f "$f" ]] || cp "$PIPELINE_DIR/elsarticle-2/$f" . 2>/dev/null || true
    done

    pdflatex -interaction=nonstopmode -halt-on-error paper > /dev/null 2>&1 && _latex_ok=1 || _latex_ok=0
    bibtex paper > /dev/null 2>&1 || true
    pdflatex -interaction=nonstopmode paper > /dev/null 2>&1 || true
    pdflatex -interaction=nonstopmode paper > /dev/null 2>&1 || true

    if grep -q "^!" paper.log 2>/dev/null; then
        log "  → LaTeX errors detected"
        return 1
    else
        log "  → Compiled cleanly"
        return 0
    fi
}

latex_error_count() {
    grep -c "^!" "$OUTPUT_DIR/paper.log" 2>/dev/null || echo 0
}

# ─────────────────────────────────────────────────────────────────────────────
# STAGE 1 — Extract style + structure ontologies
# ─────────────────────────────────────────────────────────────────────────────
run_stage 1 "01_extract_ontologies.py" "Extract ontologies"

# ─────────────────────────────────────────────────────────────────────────────
# STAGE 2 — Plan outline
# ─────────────────────────────────────────────────────────────────────────────
run_stage 2 "02_plan_paper.py" "Plan outline"

# ─────────────────────────────────────────────────────────────────────────────
# STAGE 3 — Agent writing  (LLM-heavy)
# ─────────────────────────────────────────────────────────────────────────────
run_stage 3 "03_agents_write.py" "Agents write sections"

# ─────────────────────────────────────────────────────────────────────────────
# STAGE 4 — Validation
# ─────────────────────────────────────────────────────────────────────────────
if should_run 4; then
    log "=== Stage 4: Validate draft ==="
    cd "$PIPELINE_DIR"
    "$PYTHON" 04_validate.py || {
        log "WARN: Validation reported issues — continuing (see validation_report.json)"
    }
    ok "Stage 4 done"

    if [[ -f "$OUTPUT_DIR/validation_report.json" ]]; then
        SCORE=$("$PYTHON" -c "
import json, sys
r = json.load(open('$OUTPUT_DIR/validation_report.json'))
print(f\"  citation_validity : {r.get('citation_validity',{}).get('fraction_valid','?')}\")
print(f\"  semantic_grounding: {r.get('semantic_grounding',{}).get('mean_max_sim','?'):.3f}\" if isinstance(r.get('semantic_grounding',{}).get('mean_max_sim'), float) else '')
print(f\"  composite_score   : {r.get('composite_score','?')}\")
" 2>/dev/null || true)
        log "Validation summary:"
        echo "$SCORE"
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# STAGE 5 — Render to LaTeX
# ─────────────────────────────────────────────────────────────────────────────
run_stage 5 "05_render_elsevier.py" "Render Elsevier LaTeX"

# ─────────────────────────────────────────────────────────────────────────────
# STAGE 6 — LLM LaTeX fix loop
# ─────────────────────────────────────────────────────────────────────────────
if should_run 6; then
    log "=== Stage 6: LLM LaTeX fixer (up to 6 rounds) ==="
    cd "$PIPELINE_DIR"
    "$PYTHON" 06_fix_latex.py
    EXIT_CODE=$?
    if [[ $EXIT_CODE -eq 0 ]]; then
        ok "Stage 6: LaTeX compiles cleanly"
    elif [[ $EXIT_CODE -eq 1 ]]; then
        log "WARN: Some LaTeX errors remain after fix rounds — PDF may still be usable"
    else
        fail "Stage 6: paper.tex not found"
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# STAGE 7 — Final compile + PDF summary
# ─────────────────────────────────────────────────────────────────────────────
if should_run 7; then
    log "=== Stage 7: Final compile ==="
    if compile_latex; then
        PDF="$OUTPUT_DIR/paper.pdf"
        if [[ -f "$PDF" ]]; then
            SIZE=$(du -sh "$PDF" | cut -f1)
            PAGES=$(pdfinfo "$PDF" 2>/dev/null | awk '/Pages:/{print $2}' || echo "?")
            ok "PDF ready: $PDF  ($SIZE, $PAGES pages)"
        fi
    else
        NERRS=$(latex_error_count)
        log "WARN: $NERRS LaTeX error(s) remain — PDF may be partial"
        log "Inspect: $OUTPUT_DIR/paper.log"
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
log ""
log "=== Pipeline complete ==="
log "Outputs:"
log "  draft  : $OUTPUT_DIR/draft_sections.json"
log "  tex    : $OUTPUT_DIR/paper.tex"
log "  pdf    : $OUTPUT_DIR/paper.pdf"
log "  bib    : $OUTPUT_DIR/references.bib"
log "  report : $OUTPUT_DIR/validation_report.json"
log "  log    : $LOGFILE"
