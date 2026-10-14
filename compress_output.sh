#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# compress_output.sh — Archive mineru/output_images with 7-Zip at max compression
#
# Usage:
#   ./compress_output.sh [SOURCE_DIR [OUTPUT_ARCHIVE]]
#
# Defaults:
#   SOURCE_DIR      = ./mineru/output_images
#   OUTPUT_ARCHIVE  = ./mineru_output_images_<YYYYmmdd-HHMMSS>.7z
#
# Settings explained:
#   -t7z          7z archive format
#   -m0=lzma2     LZMA2 codec (best ratio)
#   -mx=9         Ultra compression level
#   -mfb=273      Max match finder "fast bytes" (best ratio, slower)
#   -md=1536m     1.5 GiB dictionary size (needs ~ dict_size*11.5 RAM to compress)
#   -ms=on        Solid archive (better ratio for many small/similar files)
#   -mmt=on       Use all available CPU threads
#   -mqs=on       Sort files by type/extension before compressing (better ratio)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${1:-$SCRIPT_DIR/mineru/output_images}"
OUT="${2:-$SCRIPT_DIR/mineru_output_images_$(date +%Y%m%d-%H%M%S).7z}"

if ! command -v 7z &>/dev/null; then
    echo "Error: 7z not found. Install with: sudo apt-get install -y p7zip-full" >&2
    exit 1
fi

if [ ! -d "$SRC" ]; then
    echo "Error: source directory not found: $SRC" >&2
    exit 1
fi

echo "Source : $SRC"
echo "Archive: $OUT"
echo "Size before: $(du -sh "$SRC" | cut -f1)"
echo ""

7z a -t7z \
    -m0=lzma2 \
    -mx=9 \
    -mfb=273 \
    -md=1536m \
    -ms=on \
    -mmt=on \
    -mqs=on \
    "$OUT" "$SRC"

echo ""
echo "Done. Archive size: $(du -sh "$OUT" | cut -f1)"
