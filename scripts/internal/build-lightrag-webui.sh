#!/usr/bin/env bash
# Build the official LightRAG WebUI on the x86 host and deploy static assets.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/internal/common.sh"
source "$ROOT/deploy/board.env"

BOARD_SOURCE="$BOARD_APP_ROOT/third_party/LightRAG"
BOARD_ASSETS="$BOARD_SOURCE/lightrag/api/webui"
BUN_ROOT="$ROOT/third_party/bun/linux-x64"
BUN_BIN="$BUN_ROOT/bun"

if [[ ! -x "$BUN_BIN" ]]; then
  command -v curl >/dev/null || { error "curl is required to download Bun."; exit 1; }
  command -v unzip >/dev/null || { error "unzip is required to unpack Bun."; exit 1; }
  mkdir -p "$BUN_ROOT"
  archive="$(mktemp /tmp/rklight-bun.XXXXXX.zip)"
  trap 'rm -f "$archive"; rm -rf "${work:-}"' EXIT
  step "Download Bun frontend builder"
  curl --fail --location --retry 3 --output "$archive" \
    "${BUN_URL:-https://github.com/oven-sh/bun/releases/latest/download/bun-linux-x64.zip}"
  unzip -q -o "$archive" -d "$BUN_ROOT"
  if [[ -x "$BUN_ROOT/bun-linux-x64/bun" ]]; then
    mv "$BUN_ROOT/bun-linux-x64/bun" "$BUN_BIN"
    rmdir "$BUN_ROOT/bun-linux-x64"
  fi
fi
[[ -x "$BUN_BIN" ]] || { error "Bun download did not produce an executable."; exit 1; }

work="$(mktemp -d /tmp/rklight-webui.XXXXXX)"
trap 'rm -f "${archive:-}"; rm -rf "$work"' EXIT
step "Copy official WebUI source from board"
adb -s "$ADB_SERIAL" pull "$BOARD_SOURCE/lightrag_webui" "$work/lightrag_webui" >/dev/null

step "Build official LightRAG WebUI"
(
  cd "$work/lightrag_webui"
  "$BUN_BIN" install --frozen-lockfile
  "$BUN_BIN" x --bun vite build
)

[[ -f "$work/lightrag/api/webui/index.html" ]] || {
  error "LightRAG WebUI build did not create index.html."
  exit 1
}

step "Deploy WebUI static assets"
adb -s "$ADB_SERIAL" shell "rm -rf '$BOARD_ASSETS' && mkdir -p '$BOARD_ASSETS'"
adb -s "$ADB_SERIAL" push "$work/lightrag/api/webui/." "$BOARD_ASSETS/" >/dev/null
success "LightRAG WebUI assets deployed."
