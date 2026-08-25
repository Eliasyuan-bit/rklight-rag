#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$BASH_SOURCE")/../.." && pwd)"
bash "$ROOT/scripts/internal/check-config.sh"
source "$ROOT/deploy/board.env"

GATEWAY_ROOT="$BOARD_APP_ROOT/core/model-gateway"
LIGHTRAG_ENV="$BOARD_APP_ROOT/config/lightrag.env"
PARSER_ENV="$BOARD_APP_ROOT/config/pdf-parser.env"

adb -s "$ADB_SERIAL" shell "test -f '$LIGHTRAG_ENV' && test -f '$PARSER_ENV'"

adb -s "$ADB_SERIAL" shell "
  set -e
  mkdir -p '$BOARD_DATA_ROOT/logs'
  if test -f '$BOARD_DATA_ROOT/model-gateway.pid' && kill -0 \$(cat '$BOARD_DATA_ROOT/model-gateway.pid') 2>/dev/null; then
    echo 'model gateway is already running' >&2
    exit 1
  fi
  nohup sh -c '. \"$GATEWAY_ROOT/deploy/rk3588.env\"; exec python3 \"$GATEWAY_ROOT/rk1828_model_gateway.py\"' \
    > '$BOARD_DATA_ROOT/logs/model-gateway.log' 2>&1 &
  echo \$! > '$BOARD_DATA_ROOT/model-gateway.pid'
  nohup sh -c 'set -a; . \"$LIGHTRAG_ENV\"; . \"$PARSER_ENV\"; set +a; exec lightrag-server --host \"\${HOST:-0.0.0.0}\" --port \"\${PORT:-9621}\"' \
    > '$BOARD_DATA_ROOT/logs/lightrag.log' 2>&1 &
  echo \$! > '$BOARD_DATA_ROOT/lightrag.pid'
"

echo "Started model gateway and LightRAG on board $ADB_SERIAL"
