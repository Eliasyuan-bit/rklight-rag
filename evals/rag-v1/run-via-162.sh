#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SSH_TARGET="${RAG_EVAL_SSH_TARGET:-rockchip-yn@172.16.15.162}"
ADB_SERIAL="${RAG_EVAL_ADB_SERIAL:-32a331f9ae73952d}"
LOCAL_PORT="${RAG_EVAL_LOCAL_PORT:-19621}"
REMOTE_PORT="${RAG_EVAL_REMOTE_PORT:-19621}"
TUNNEL_PID=""

cleanup() {
  if [[ -n "$TUNNEL_PID" ]]; then
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
  fi
  ssh -o BatchMode=yes "$SSH_TARGET" \
    "adb -s '$ADB_SERIAL' forward --remove tcp:$REMOTE_PORT" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

ssh -o BatchMode=yes "$SSH_TARGET" \
  "adb -s '$ADB_SERIAL' forward tcp:$REMOTE_PORT tcp:9621" >/dev/null

ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes \
  -L "127.0.0.1:$LOCAL_PORT:127.0.0.1:$REMOTE_PORT" \
  "$SSH_TARGET" &
TUNNEL_PID=$!

for _ in 1 2 3 4 5; do
  if python3 - "$LOCAL_PORT" <<'PY'
import sys
from urllib.request import urlopen
try:
    urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=2).close()
except Exception:
    raise SystemExit(1)
PY
  then
    exec_status=0
    python3 "$SCRIPT_DIR/run_eval.py" --url "http://127.0.0.1:$LOCAL_PORT" "$@" || exec_status=$?
    exit "$exec_status"
  fi
  sleep 1
done

echo "LightRAG health check failed through $SSH_TARGET / ADB $ADB_SERIAL" >&2
exit 1
