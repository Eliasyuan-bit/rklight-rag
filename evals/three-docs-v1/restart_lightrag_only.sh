#!/bin/sh
set -eu

app=/userdata/rklight-rag
data=/userdata/lightrag-data
pid_file="$data/lightrag.pid"
if test -f "$pid_file"; then
    pid=$(cat "$pid_file")
    case "$pid" in *[!0-9]*|'') echo "invalid LightRAG pid: $pid" >&2; exit 1;; esac
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            kill -0 "$pid" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$pid" 2>/dev/null; then
            echo "LightRAG PID $pid did not stop" >&2
            exit 1
        fi
    fi
fi
cd "$app"
nohup sh -c 'cd /userdata/rklight-rag; set -a; . config/lightrag.env; . config/pdf-parser.env; set +a; exec /userdata/rklight-rag/venv/bin/lightrag-server --host "${HOST:-0.0.0.0}" --port "${PORT:-9621}"' > "$data/logs/lightrag.log" 2>&1 < /dev/null &
echo $! > "$pid_file"
echo "LightRAG restarted: $(cat "$pid_file")"
