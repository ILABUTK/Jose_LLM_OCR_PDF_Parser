#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# process_all.sh — Batch-process every file in input_images with MinerU
#
# Features:
#   • Auto-detects all supported formats (PDF, PNG, JPG, DOCX, PPTX, XLSX)
#   • --continue behaviour: skips files whose output directory already exists
#   • Backend configurable via BACKEND env var (default: pipeline)
#
# Usage inside container:
#   process_all.sh [INPUT_DIR [OUTPUT_DIR]]
#
# Environment variables:
#   BACKEND      pipeline (default, CPU/GPU) | hybrid-auto-engine | vlm-auto-engine
#   INPUT_DIR    override input  directory   (default: /workspace/input_images)
#   OUTPUT_DIR   override output directory   (default: /workspace/output_images)
# ─────────────────────────────────────────────────────────────────────────────

INPUT_DIR="${1:-${INPUT_DIR:-/workspace/input_images}}"
OUTPUT_DIR="${2:-${OUTPUT_DIR:-/workspace/output_images}}"
BACKEND="${BACKEND:-hybrid-auto-engine}"  # GPU VLM engine; set BACKEND=pipeline for CPU-only

export MINERU_MODEL_SOURCE=local

echo "╔══════════════════════════════════════════╗"
echo "║       MinerU Batch Processor             ║"
echo "╚══════════════════════════════════════════╝"
echo "  MinerU : $(mineru -v 2>/dev/null || echo 'unknown')"
echo "  Input  : $INPUT_DIR"
echo "  Output : $OUTPUT_DIR"
echo "  Backend: $BACKEND"
echo ""

mkdir -p "$OUTPUT_DIR"

# ── Collect all supported files ───────────────────────────────────────────────
shopt -s nullglob
files=()
for ext in pdf PDF png PNG jpg JPG jpeg JPEG docx DOCX pptx PPTX xlsx XLSX; do
    for f in "$INPUT_DIR"/*."$ext"; do
        [ -f "$f" ] && files+=("$f")
    done
done

total=${#files[@]}
if [ "$total" -eq 0 ]; then
    echo "No supported files found in $INPUT_DIR"
    echo "Supported formats: PDF, PNG, JPG, JPEG, DOCX, PPTX, XLSX"
    exit 0
fi

echo "Found $total file(s)."
echo ""

processed=0
skipped=0
failed=0
idx=0

for file in "${files[@]}"; do
    idx=$((idx + 1))
    filename=$(basename "$file")
    stem="${filename%.*}"

    # ── --continue: skip if the output folder already exists with content ─────
    if [ -d "$OUTPUT_DIR/$stem" ] && [ -n "$(ls -A "$OUTPUT_DIR/$stem" 2>/dev/null)" ]; then
        echo "[$idx/$total] SKIP  (already done) → $filename"
        skipped=$((skipped + 1))
        continue
    fi

    echo "[$idx/$total] RUN   $filename"
    if mineru -p "$file" -o "$OUTPUT_DIR" -b "$BACKEND"; then
        echo "[$idx/$total] OK    $filename"
        processed=$((processed + 1))
    else
        echo "[$idx/$total] FAIL  $filename"
        failed=$((failed + 1))
    fi
    echo ""
done

echo "──────────────────────────────────────────"
echo "  Processed : $processed"
echo "  Skipped   : $skipped  (already done — re-run will skip again)"
echo "  Failed    : $failed"
echo "──────────────────────────────────────────"

[ "$failed" -eq 0 ] && exit 0 || exit 1
