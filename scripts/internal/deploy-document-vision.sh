#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$BASH_SOURCE")/../.." && pwd)"
bash "$ROOT/scripts/internal/check-config.sh"
source "$ROOT/deploy/board.env"

export ADB_SERIAL
export TARGET_ROOT="$BOARD_APP_ROOT/document-vision"
exec bash "$ROOT/core/document-vision/scripts/deploy-adb.sh"
