#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${RK_LIGHTRAG_ROOT:-/userdata/rklight-rag}"
DATA_ROOT="${RK_LIGHTRAG_DATA_ROOT:-/userdata/lightrag-data}"
GATEWAY_ROOT="$APP_ROOT/core/model-gateway"
LIGHTRAG_ENV="$APP_ROOT/config/lightrag.env"
PARSER_ENV="$APP_ROOT/config/pdf-parser.env"

start_service() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  local command="$4"

  if [[ -f "$pid_file" ]] && kill -0 "$(<"$pid_file")" 2>/dev/null; then
    echo "$name is already running (pid $(<"$pid_file"))."
    return
  fi

  nohup sh -c "$command" >"$log_file" 2>&1 &
  echo $! >"$pid_file"
  echo "Started $name (pid $!)."
}

[[ -f "$LIGHTRAG_ENV" ]] || { echo "Missing $LIGHTRAG_ENV" >&2; exit 1; }
[[ -f "$PARSER_ENV" ]] || { echo "Missing $PARSER_ENV" >&2; exit 1; }
command -v lightrag-server >/dev/null || { echo "lightrag-server is not installed" >&2; exit 1; }

mkdir -p "$DATA_ROOT/logs"

start_service \
  "model gateway" \
  "$DATA_ROOT/model-gateway.pid" \
  "$DATA_ROOT/logs/model-gateway.log" \
  ". '$GATEWAY_ROOT/deploy/rk3588.env'; exec python3 '$GATEWAY_ROOT/rk1828_model_gateway.py'"

start_service \
  "LightRAG" \
  "$DATA_ROOT/lightrag.pid" \
  "$DATA_ROOT/logs/lightrag.log" \
  "set -a; . '$LIGHTRAG_ENV'; . '$PARSER_ENV'; set +a; exec lightrag-server --host \"\${HOST:-0.0.0.0}\" --port \"\${PORT:-9621}\""

echo "WebUI: http://<board-ip>:9621"
