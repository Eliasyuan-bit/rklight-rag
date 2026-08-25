#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/deploy/board.env"
# shellcheck disable=SC1091
source "$ROOT/deploy/lightrag-upstream.env"

TARGET="$BOARD_APP_ROOT/third_party/LightRAG"
adb -s "$ADB_SERIAL" shell "mkdir -p '$BOARD_APP_ROOT/third_party'"

if adb -s "$ADB_SERIAL" shell "test -d '$TARGET/.git'"; then
  adb -s "$ADB_SERIAL" shell "git -C '$TARGET' fetch --depth 1 origin '$LIGHTRAG_UPSTREAM_REVISION' && git -C '$TARGET' checkout --detach '$LIGHTRAG_UPSTREAM_REVISION'"
else
  adb -s "$ADB_SERIAL" shell "git clone --depth 1 '$LIGHTRAG_UPSTREAM_URL' '$TARGET' && git -C '$TARGET' fetch --depth 1 origin '$LIGHTRAG_UPSTREAM_REVISION' && git -C '$TARGET' checkout --detach '$LIGHTRAG_UPSTREAM_REVISION'"
fi

adb -s "$ADB_SERIAL" shell "
  set -e
  python3 -m pip install --disable-pip-version-check --upgrade -e '$TARGET[api]'
  command -v lightrag-server
  python3 -c 'import lightrag; print(lightrag.__file__)'
"

echo "Official LightRAG $LIGHTRAG_UPSTREAM_REVISION installed from $TARGET on board."
