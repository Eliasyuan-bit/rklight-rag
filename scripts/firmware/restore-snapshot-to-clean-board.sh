#!/usr/bin/env bash
# Restore the captured application stack after an EVB10 system image is flashed.
# An optional, separately archived knowledge base is installed before services start.
# Never use on a board with an existing application or knowledge base.
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 SNAPSHOT_DIR ADB_SERIAL [--kg-backup DIR] [--apply]" >&2
  exit 2
fi
snapshot=$(realpath "$1")
serial=$2
shift 2
apply=0
kg_backup=
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) apply=1; shift ;;
    --kg-backup)
      [[ $# -ge 2 ]] || { echo "--kg-backup needs a directory" >&2; exit 2; }
      kg_backup=$(realpath "$2")
      shift 2
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
case "$snapshot" in /tmp|/tmp/*) echo "Refusing /tmp snapshot" >&2; exit 2 ;; esac
case "$kg_backup" in /tmp|/tmp/*) echo "Refusing /tmp knowledge-base backup" >&2; exit 2 ;; esac

script_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
export TMPDIR="$script_root/runtime/tmp" TMP="$script_root/runtime/tmp" TEMP="$script_root/runtime/tmp"
mkdir -p "$TMPDIR"

bash "$script_root/scripts/firmware/verify-snapshot.sh" "$snapshot"
if [[ -n "$kg_backup" ]]; then
  test -d "$kg_backup/lightrag-data"
  test -s "$kg_backup/COPY_SHA256SUMS"
  if [[ -f "$kg_backup/BOARD_SHA256SUMS" ]]; then
    cmp "$kg_backup/BOARD_SHA256SUMS" "$kg_backup/COPY_SHA256SUMS"
  fi
  (cd "$kg_backup/lightrag-data" && sha256sum --quiet --check "$kg_backup/COPY_SHA256SUMS")
fi
adb -s "$serial" get-state | grep -qx device
model=$(adb -s "$serial" shell cat /proc/device-tree/model | tr -d '\000\r')
kernel=$(adb -s "$serial" shell uname -r | tr -d '\r')
[[ "$model" == *"RK3588 EVB10 V10"* ]] || { echo "Unexpected board: $model" >&2; exit 1; }
[[ "$kernel" == 6.1.172 ]] || { echo "Unexpected kernel: $kernel" >&2; exit 1; }

if adb -s "$serial" shell test -e /userdata/rklight-rag; then
  echo "Refusing to overwrite an existing /userdata/rklight-rag installation" >&2
  exit 1
fi
if adb -s "$serial" shell test -e /userdata/lightrag-data; then
  echo "Refusing a board with an existing knowledge base; use a separate preservation procedure" >&2
  exit 1
fi

if (( ! apply )); then
  echo "Dry run: snapshot verified; target is $model ($kernel)."
  echo "Would install the captured application, model/vision directories, RKNN runtime binaries and startup units."
  if [[ -n "$kg_backup" ]]; then
    echo "Would restore the separately verified knowledge base before starting services."
  else
    echo "No knowledge-base backup specified; the original UCM630x index would not be restored."
  fi
  echo "Add --apply to perform the installation on this clean board."
  exit 0
fi

for name in \
  rklight-rag \
  Qwen3.5-2B \
  RK1828-qwen3.5-4b-service \
  RK1828-qwen3-embedding-reranker-service \
  document-vision-service \
  ppocrv6-rknn-service \
  doclayout-yolo-rknn-service; do
  adb -s "$serial" push "$snapshot/userdata/$name" /userdata/
done

# adb pull/push dereferences symlinks. The captured lib64 is therefore a
# duplicate directory; remove only that freshly pushed copy before restoring
# the original link recorded in board-app-symlinks.txt.
adb -s "$serial" shell 'test -d /userdata/rklight-rag/venv/lib64 && test ! -L /userdata/rklight-rag/venv/lib64 && rm -r /userdata/rklight-rag/venv/lib64'
adb -s "$serial" shell 'ln -sfn config/lightrag.env /userdata/rklight-rag/.env; ln -sfn lib /userdata/rklight-rag/venv/lib64; ln -sfn /usr/bin/python3 /userdata/rklight-rag/venv/bin/python3; ln -sfn python3 /userdata/rklight-rag/venv/bin/python3.11; ln -sfn python3 /userdata/rklight-rag/venv/bin/python'

for path in \
  /usr/bin/rkllm3-server \
  /usr/lib/librknn3_api_rkcp.so \
  /usr/lib/librknn3_api.so \
  /usr/lib/librknn3_downloader.so \
  /usr/lib/librknnsmi.so \
  /usr/lib/librknnrt.so; do
  adb -s "$serial" push "$snapshot$path" "$path"
done
adb -s "$serial" shell chmod 755 /usr/bin/rkllm3-server

adb -s "$serial" push "$script_root/core/board-launcher/run-model-gateway" /userdata/rklight-rag/bin/
adb -s "$serial" push "$script_root/core/board-launcher/run-lightrag" /userdata/rklight-rag/bin/
adb -s "$serial" shell chmod 755 /userdata/rklight-rag/bin/run-model-gateway /userdata/rklight-rag/bin/run-lightrag
adb -s "$serial" push "$script_root/deploy/systemd/rklight-model-gateway.service" /etc/systemd/system/
adb -s "$serial" push "$script_root/deploy/systemd/rklight-lightrag.service" /etc/systemd/system/
if [[ -n "$kg_backup" ]]; then
  adb -s "$serial" push "$kg_backup/lightrag-data" /userdata/
  cmp "$kg_backup/COPY_SHA256SUMS" <(
    adb -s "$serial" shell 'cd /userdata/lightrag-data && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum' | tr -d '\r'
  ) || { echo "Restored knowledge-base files differ; services were not started" >&2; exit 1; }
fi
adb -s "$serial" shell systemctl daemon-reload
adb -s "$serial" shell systemctl enable --now rklight-model-gateway.service rklight-lightrag.service
for _ in $(seq 1 60); do
  if adb -s "$serial" shell 'curl -fsS --max-time 2 http://127.0.0.1:8100/health >/dev/null && curl -fsS --max-time 2 http://127.0.0.1:9621/health >/dev/null'; then
    echo "Application stack restored. Knowledge base: $([[ -n "$kg_backup" ]] && echo verified-backup || echo empty)."
    exit 0
  fi
  sleep 2
done
echo "Services did not become healthy; inspect journalctl on the board" >&2
exit 1
