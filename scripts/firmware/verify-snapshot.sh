#!/usr/bin/env bash
set -euo pipefail

snapshot=${1:?Usage: verify-snapshot.sh SNAPSHOT_DIR}
snapshot=$(realpath "$snapshot")
case "$snapshot" in /tmp|/tmp/*) echo "Refusing /tmp snapshot" >&2; exit 2 ;; esac
test -f "$snapshot/SHA256SUMS"
test -d "$snapshot/userdata/rklight-rag"
test -f "$snapshot/userdata/rklight-rag/config/lightrag.env"
test -f "$snapshot/userdata/Qwen3.5-2B/Qwen3.5-2B.weight"
test -f "$snapshot/userdata/RK1828-qwen3.5-4b-service/models/Qwen3.5-4B/Qwen3.5-4B.weight"
test -f "$snapshot/userdata/RK1828-qwen3-embedding-reranker-service/models/qwen3-embedding-0.6b/Qwen3-Embedding-0.6B.weight"
test -f "$snapshot/userdata/RK1828-qwen3-embedding-reranker-service/models/qwen3-reranker-0.6b/Qwen3-Reranker-0.6B.weight"
test -f "$snapshot/usr/bin/rkllm3-server"
test -s "$snapshot/deploy/patches/lightrag-7ecd8a0-board.patch"
test ! -e "$snapshot/userdata/lightrag-data" || {
  echo "Knowledge-base data was accidentally included" >&2
  exit 1
}

(
  cd "$snapshot"
  sha256sum --quiet --check SHA256SUMS
)
echo "Snapshot verified: $snapshot"
