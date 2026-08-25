#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$BASH_SOURCE")/../.." && pwd)"
source "$ROOT/scripts/internal/common.sh"
bash "$ROOT/scripts/internal/check-config.sh"
source "$ROOT/deploy/board.env"

# Keep existing deployments compatible with board.env files created before
# these two optional port settings were added.
MODEL_GATEWAY_PORT="${MODEL_GATEWAY_PORT:-8100}"
LIGHTRAG_PORT="${LIGHTRAG_PORT:-9621}"

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

wait_for_health() {
  local name="$1" url="$2" deadline=$((SECONDS + 90))
  while (( SECONDS < deadline )); do
    if curl --fail --silent "$url" >/dev/null; then
      success "$name is ready."
      return 0
    fi
    sleep 2
  done
  error "$name did not become ready within 90 seconds."
  exit 1
}

wait_for_health "Model gateway" "http://127.0.0.1:$MODEL_GATEWAY_PORT/health"
# /query/status is provided by the installed LightRAG hook and remains usable
# before any document has been uploaded; unlike a version-dependent /health
# route, it is a reliable readiness check for this deployment.
wait_for_health "LightRAG" "http://127.0.0.1:$LIGHTRAG_PORT/query/status"
echo "Board deployment verification: OK"
