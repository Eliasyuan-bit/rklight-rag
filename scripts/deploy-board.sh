#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash "$ROOT/scripts/check-config.sh"

# shellcheck disable=SC1091
source "$ROOT/deploy/board.env"

PARSER_MODE="${RK_PDF_PARSER_MODE:-${PDF_PARSER_MODE:-cloud}}"
case "$PARSER_MODE" in cloud|rkvision) ;; *) echo "PDF parser mode must be cloud or rkvision, got: $PARSER_MODE" >&2; exit 2 ;; esac

adb -s "$ADB_SERIAL" shell "mkdir -p '$BOARD_APP_ROOT/config' '$BOARD_APP_ROOT/components' '$BOARD_APP_ROOT/core/model-gateway' '$BOARD_APP_ROOT/core/lightrag-extensions' '$BOARD_APP_ROOT/core/ingest-router' '$BOARD_APP_ROOT/core/rkvision-parser' '$BOARD_DATA_ROOT'"
adb -s "$ADB_SERIAL" shell "mkdir -p '$BOARD_APP_ROOT/bin'"
adb -s "$ADB_SERIAL" push "$ROOT/deploy/lightrag.env" "$BOARD_APP_ROOT/config/lightrag.env" >/dev/null
adb -s "$ADB_SERIAL" push "$ROOT/deploy/parser-profiles/$PARSER_MODE.env" "$BOARD_APP_ROOT/config/pdf-parser.env" >/dev/null
adb -s "$ADB_SERIAL" push "$ROOT/core/model-gateway/." "$BOARD_APP_ROOT/core/model-gateway/" >/dev/null
adb -s "$ADB_SERIAL" push "$ROOT/core/lightrag-extensions/." "$BOARD_APP_ROOT/core/lightrag-extensions/" >/dev/null
adb -s "$ADB_SERIAL" push "$ROOT/core/ingest-router/." "$BOARD_APP_ROOT/core/ingest-router/" >/dev/null
adb -s "$ADB_SERIAL" push "$ROOT/scripts/board-start.sh" "$BOARD_APP_ROOT/bin/start-rklight-rag" >/dev/null
adb -s "$ADB_SERIAL" shell "chmod +x '$BOARD_APP_ROOT/bin/start-rklight-rag'"
if [[ "$PARSER_MODE" == "rkvision" ]]; then
  adb -s "$ADB_SERIAL" push "$ROOT/core/rkvision-parser/." "$BOARD_APP_ROOT/core/rkvision-parser/" >/dev/null
fi

echo "Core code and '$PARSER_MODE' PDF parser profile copied to $BOARD_APP_ROOT."
echo "Build/deploy each model-service release artifact first."
echo "For the optional PDF sidecar: ./scripts/build-document-vision.sh && ./scripts/deploy-document-vision.sh"
echo "Then run:"
echo "  ./scripts/install-lightrag-upstream.sh"
echo "  ./scripts/install-lightrag-extensions.sh"
echo "  ./scripts/start-board.sh"
echo "  ./scripts/verify-board.sh"
