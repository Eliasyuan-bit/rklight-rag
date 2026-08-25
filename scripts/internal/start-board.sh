#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$BASH_SOURCE")/../.." && pwd)"
RESTART=false
if [[ "${1:-}" == "--restart" ]]; then
  RESTART=true
  shift
fi
[[ $# -eq 0 ]] || { echo "Usage: $0 [--restart]" >&2; exit 2; }

bash "$ROOT/scripts/internal/check-config.sh"
source "$ROOT/deploy/board.env"

GATEWAY_ROOT="$BOARD_APP_ROOT/core/model-gateway"
LIGHTRAG_ENV="$BOARD_APP_ROOT/config/lightrag.env"
PARSER_ENV="$BOARD_APP_ROOT/config/pdf-parser.env"
LIGHTRAG_SERVER="$BOARD_APP_ROOT/venv/bin/lightrag-server"

adb -s "$ADB_SERIAL" shell "test -f '$LIGHTRAG_ENV' && test -f '$PARSER_ENV' && test -x '$LIGHTRAG_SERVER'"

adb -s "$ADB_SERIAL" shell "
  set -e
  mkdir -p '$BOARD_DATA_ROOT/logs'
  # LightRAG checks the current working directory for .env before startup.
  # Keep the deployed configuration in config/, but expose it at the location
  # required by the upstream server without duplicating configuration.
  ln -sfn 'config/lightrag.env' '$BOARD_APP_ROOT/.env'
  if $RESTART; then
    for name in model-gateway lightrag; do
      pid_file='$BOARD_DATA_ROOT/'\$name.pid
      if test -f \"\$pid_file\" && kill -0 \$(cat \"\$pid_file\") 2>/dev/null; then
        kill \$(cat \"\$pid_file\")
        for _ in 1 2 3 4 5 6 7 8 9 10; do
          kill -0 \$(cat \"\$pid_file\") 2>/dev/null || break
          sleep 1
        done
      fi
    done
  fi
  if test -f '$BOARD_DATA_ROOT/model-gateway.pid' && kill -0 \$(cat '$BOARD_DATA_ROOT/model-gateway.pid') 2>/dev/null; then
    echo 'model gateway is already running'
  else
    nohup sh -c '. \"$GATEWAY_ROOT/deploy/rk3588.env\"; exec python3 \"$GATEWAY_ROOT/rk1828_model_gateway.py\"' \
      > '$BOARD_DATA_ROOT/logs/model-gateway.log' 2>&1 &
    echo \$! > '$BOARD_DATA_ROOT/model-gateway.pid'
  fi
  if test -f '$BOARD_DATA_ROOT/lightrag.pid' && kill -0 \$(cat '$BOARD_DATA_ROOT/lightrag.pid') 2>/dev/null; then
    echo 'LightRAG is already running'
  else
    nohup sh -c 'cd \"$BOARD_APP_ROOT\"; set -a; . \"$LIGHTRAG_ENV\"; . \"$PARSER_ENV\"; set +a; exec \"$LIGHTRAG_SERVER\" --host \"\${HOST:-0.0.0.0}\" --port \"\${PORT:-9621}\"' \
      > '$BOARD_DATA_ROOT/logs/lightrag.log' 2>&1 &
    echo \$! > '$BOARD_DATA_ROOT/lightrag.pid'
  fi
  sleep 2
  for name in model-gateway lightrag; do
    pid_file='$BOARD_DATA_ROOT/'\$name.pid
    if ! kill -0 \$(cat \"\$pid_file\") 2>/dev/null; then
      echo \"[ERROR] \$name exited during startup.\" >&2
      tail -n 40 '$BOARD_DATA_ROOT/logs/'\$name.log >&2 || true
      exit 1
    fi
  done
"

echo "Started model gateway and LightRAG on board $ADB_SERIAL"
