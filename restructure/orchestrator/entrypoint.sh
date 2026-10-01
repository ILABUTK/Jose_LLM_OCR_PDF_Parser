#!/usr/bin/env bash
# Entrypoint for the orchestrator container.
# PIPELINE_MODE selects between:
#   pipeline  (default) — deterministic graph-of-thought traversal (pipeline.py)
#   agent               — LLM drives the MCP tools itself (agent.py)
#   idle                — stay up so stages can be triggered via `docker exec`
set -euo pipefail

cd /app/orchestrator

MODE="${PIPELINE_MODE:-pipeline}"
echo "[entrypoint] mode=$MODE  LLM=$LLM_MODEL  GRAPH_DEPTH=${GRAPH_DEPTH:-3}  PAPER_IMAGE_COUNT=${PAPER_IMAGE_COUNT:-2}"

case "$MODE" in
  pipeline) exec python pipeline.py ;;
  agent)    exec python agent.py ;;
  idle)     echo "[entrypoint] idle — trigger with: docker exec -it paper-orchestrator python pipeline.py"
            exec tail -f /dev/null ;;
  *)        echo "[entrypoint] unknown PIPELINE_MODE=$MODE"; exit 1 ;;
esac
