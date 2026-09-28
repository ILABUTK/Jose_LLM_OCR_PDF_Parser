#!/bin/bash
# mineru_entrypoint.sh
# Ensures MinerU pipeline models AND /root/mineru.json config are in place.
# Weights live in /models (bind-mounted → persist). The JSON config lives in
# /root/ which is NOT persisted, so we recreate it on every start if missing.
# mineru-models-download is idempotent: it skips files that already exist in
# /models and just rewrites the small JSON, which is fast.

set -e

if [ ! -f /root/mineru.json ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo " /root/mineru.json missing — running mineru-models-download"
    echo " (will skip already-cached weights in /models, just rewrites config)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    mineru-models-download -s huggingface -m pipeline
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo " MinerU config ready."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
    echo "MinerU config /root/mineru.json present — skipping download."
fi

export MINERU_MODEL_SOURCE=local
export MINERU_MODELS_DIR=/models

exec "$@"
