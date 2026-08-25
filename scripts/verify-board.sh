#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$BASH_SOURCE")/.." && pwd)"
"$ROOT/scripts/check-config.sh"
source "$ROOT/deploy/board.env"

adb -s "$ADB_SERIAL" shell "
  set -e
  test -f '$BOARD_APP_ROOT/config/lightrag.env'
  test -f '$BOARD_APP_ROOT/core/model-gateway/rk1828_model_gateway.py'
  test -x '$VECTOR_SERVICE_ROOT/bin/rk1828_embedding_daemon'
  test -x '$VECTOR_SERVICE_ROOT/bin/rk1828_reranker_daemon'
  test -x '$LLM_SERVICE_ROOT/bin/rk1828_qwen35_9b_2cards_daemon' -o -x '$LLM_SERVICE_ROOT/bin/multicard/rknn_multicard_demo'
"

adb -s "$ADB_SERIAL" forward tcp:"$MODEL_GATEWAY_PORT" tcp:"$MODEL_GATEWAY_PORT" >/dev/null
adb -s "$ADB_SERIAL" forward tcp:"$LIGHTRAG_PORT" tcp:"$LIGHTRAG_PORT" >/dev/null
curl --fail --silent "http://127.0.0.1:$MODEL_GATEWAY_PORT/health"
curl --fail --silent "http://127.0.0.1:$LIGHTRAG_PORT/health" >/dev/null
echo "Board deployment verification: OK"
