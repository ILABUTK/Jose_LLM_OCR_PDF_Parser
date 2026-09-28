#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# docker_run.sh — One command to process all files in mineru/input_images
#
# Usage:
#   ./docker_run.sh                        # GPU + hybrid-auto-engine (default)
#   BACKEND=pipeline ./docker_run.sh       # CPU-only / pipeline backend
#   BACKEND=vlm-auto-engine ./docker_run.sh
#
# Volumes mounted automatically:
#   ./mineru/PDFs/files    → /workspace/input_images   (numbered subfolders, each with one PDF)
#   ./mineru/output_images → /workspace/output_images  (results appear here, one folder per ref#)
#
# The script skips files already processed (--continue behaviour).
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="${BACKEND:-hybrid-auto-engine}"  # GPU VLM engine; override with BACKEND=pipeline for CPU

# ── Build image if it doesn't exist yet ───────────────────────────────────────
if ! docker image inspect mineru:latest &>/dev/null; then
    echo "Image 'mineru:latest' not found — building now (this takes a while the first time)..."
    docker build -t mineru:latest "$SCRIPT_DIR" || { echo "Build failed."; exit 1; }
fi

docker run --gpus all \
    --shm-size 16g \
    --rm \
    -e BACKEND="$BACKEND" \
    -v "$SCRIPT_DIR/mineru/PDFs/files:/workspace/input_images" \
    -v "$SCRIPT_DIR/mineru/output_images:/workspace/output_images" \
    mineru:latest \
    process_all.sh
