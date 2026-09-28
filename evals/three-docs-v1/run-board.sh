#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
RESULT_ROOT="${RAG_EVAL_RESULT_ROOT:-/userdata/lightrag-data/eval-results}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RESULT_ROOT"

exec python3 "$SCRIPT_DIR/run_eval.py" \
  --url "${RAG_EVAL_URL:-http://127.0.0.1:9621}" \
  --output "$RESULT_ROOT/three-docs-$TIMESTAMP.json" \
  "$@"
