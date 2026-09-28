#!/bin/sh
set -eu

work_dir=${RK_BENCHMARK_WORK_DIR:-/userdata/rklight-rag/runtime/benchmark}
server_script=${RK_BENCHMARK_SERVER_SCRIPT:-"$work_dir/run_4b_benchmark_server.sh"}
mkdir -p "$work_dir"
pid_file="$work_dir/rag_4b_benchmark_server.pid"
log_file="$work_dir/rag_4b_benchmark_server.log"
test -f "$server_script" || { echo "Missing benchmark server script: $server_script" >&2; exit 1; }
if test -f "$pid_file"; then
    existing=$(cat "$pid_file")
    if kill -0 "$existing" 2>/dev/null; then
        echo "4B benchmark server is already running: $existing"
        exit 0
    fi
fi
nohup sh "$server_script" > "$log_file" 2>&1 < /dev/null &
echo $! > "$pid_file"
sleep 1
kill -0 "$(cat "$pid_file")"
echo "4B benchmark server started: $(cat "$pid_file")"
