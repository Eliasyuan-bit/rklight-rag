#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

for file in "$ROOT/deploy/board.env" "$ROOT/deploy/lightrag.env"; do
  if [[ ! -f "$file" ]]; then
    error "Missing configuration file: $file"
    hint "cp ${file}.example ${file}"
    exit 1
  fi
done

# shellcheck disable=SC1091
source "$ROOT/deploy/board.env"

if [[ "${ADB_SERIAL:-}" == "192.168.1.100:5555" ]]; then
  error "deploy/board.env still uses the example ADB_SERIAL."
  hint "Set ADB_SERIAL to the real board, for example: 172.16.15.195:5555"
  exit 1
fi

command -v adb >/dev/null || { error "adb was not found in PATH."; exit 1; }
adb -s "$ADB_SERIAL" get-state >/dev/null || { error "Cannot connect to ADB device: $ADB_SERIAL"; exit 1; }

echo "Configuration is syntactically ready for board: $ADB_SERIAL"
