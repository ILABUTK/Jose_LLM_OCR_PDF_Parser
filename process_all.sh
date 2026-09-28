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

# ── Collect files: support both flat and numbered-subdir structures ───────────
#
#   Flat   (old): INPUT_DIR/paper.pdf   → output key = "paper"
#   Subdir (new): INPUT_DIR/1671/foo.pdf → output key = "1671"
#
shopt -s nullglob
declare -a files=()
declare -a keys=()

# 1) Flat files at the root of INPUT_DIR
for ext in pdf PDF png PNG jpg JPG jpeg JPEG docx DOCX pptx PPTX xlsx XLSX; do
    for f in "$INPUT_DIR"/*."$ext"; do
        [ -f "$f" ] || continue
        files+=("$f")
        stem=$(basename "$f"); keys+=("${stem%.*}")
    done
done

# 2) Numbered subdirectory structure: INPUT_DIR/NNNN/paper.pdf
#    Uses the directory name (e.g. "1671") as the output key.
for subdir in "$INPUT_DIR"/*/; do
    [ -d "$subdir" ] || continue
    ref_key=$(basename "$subdir")
    found=0
    for ext in pdf PDF png PNG jpg JPG jpeg JPEG docx DOCX pptx PPTX xlsx XLSX; do
        for f in "$subdir"*."$ext"; do
            [ -f "$f" ] || continue
            files+=("$f")
            keys+=("$ref_key")
            found=1
            break 2
        done
    done
    if [ "$found" -eq 0 ]; then
        echo "WARN  no supported file in $subdir"
    fi
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

for i in "${!files[@]}"; do
    file="${files[$i]}"
    key="${keys[$i]}"
    idx=$((idx + 1))
    filename=$(basename "$file")

    # ── --continue: skip if the output folder already exists with content ─────
    if [ -d "$OUTPUT_DIR/$key" ] && [ -n "$(ls -A "$OUTPUT_DIR/$key" 2>/dev/null)" ]; then
        echo "[$idx/$total] SKIP  (already done) → $key ($filename)"
        skipped=$((skipped + 1))
        continue
    fi

    # If the key differs from the file stem (subdir mode), use a temp copy so
    # MinerU names the output folder after the key rather than the filename.
    file_stem="${filename%.*}"
    if [ "$key" != "$file_stem" ]; then
        tmp_file="/tmp/${key}.${filename##*.}"
        cp "$file" "$tmp_file"
        process_file="$tmp_file"
    else
        process_file="$file"
        tmp_file=""
    fi

    echo "[$idx/$total] RUN   $key  ($filename)"
    if mineru -p "$process_file" -o "$OUTPUT_DIR" -b "$BACKEND" -t false; then
        echo "[$idx/$total] OK    $key"
        processed=$((processed + 1))
    else
        echo "[$idx/$total] FAIL  $key"
        failed=$((failed + 1))
    fi

    # Clean up temp copy
    [ -n "$tmp_file" ] && rm -f "$tmp_file"
    echo ""
done

echo "──────────────────────────────────────────"
echo "  Processed : $processed"
echo "  Skipped   : $skipped  (already done — re-run will skip again)"
echo "  Failed    : $failed"
echo "──────────────────────────────────────────"

[ "$failed" -eq 0 ] && exit 0 || exit 1
