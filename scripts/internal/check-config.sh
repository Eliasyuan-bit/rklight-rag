#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

for file in "$ROOT/deploy/board.env" "$ROOT/deploy/lightrag.env"; do
  if [[ ! -f "$file" ]]; then
    error "缺少配置文件：$file"
    hint "cp ${file}.example ${file}"
    exit 1
  fi
done

# shellcheck disable=SC1091
source "$ROOT/deploy/board.env"

if [[ "${ADB_SERIAL:-}" == "192.168.1.100:5555" ]]; then
  error "deploy/board.env 仍在使用示例 ADB_SERIAL。"
  hint "将 ADB_SERIAL 改为实际板端，例如：172.16.15.195:5555"
  exit 1
fi

command -v adb >/dev/null || { error "未找到 adb。"; exit 1; }
adb -s "$ADB_SERIAL" get-state >/dev/null || { error "无法连接 ADB 设备：$ADB_SERIAL"; exit 1; }

echo "Configuration is syntactically ready for board: $ADB_SERIAL"
