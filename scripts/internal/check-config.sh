#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

for file in "$ROOT/deploy/board.env" "$ROOT/deploy/lightrag.env"; do
  if [[ ! -f "$file" ]]; then
    echo "Missing $file; copy its .example file first." >&2
    exit 1
  fi
done

# shellcheck disable=SC1091
source "$ROOT/deploy/board.env"

if [[ "${ADB_SERIAL:-}" == "192.168.1.100:5555" ]]; then
  echo "Set ADB_SERIAL in deploy/board.env." >&2
  exit 1
fi

command -v adb >/dev/null || { echo "adb is required." >&2; exit 1; }
adb -s "$ADB_SERIAL" get-state >/dev/null

echo "Configuration is syntactically ready for board: $ADB_SERIAL"
