#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$BASH_SOURCE")/../.." && pwd)"
bash "$ROOT/scripts/internal/check-config.sh"
source "$ROOT/deploy/board.env"

PARSER_MODE="${RK_PDF_PARSER_MODE:-${PDF_PARSER_MODE:-cloud}}"
case "$PARSER_MODE" in cloud|rkvision) ;; *) echo "PDF parser mode must be cloud or rkvision, got: $PARSER_MODE" >&2; exit 2 ;; esac

EXT_ROOT="$BOARD_APP_ROOT/core/lightrag-extensions"
adb -s "$ADB_SERIAL" shell "
  set -e
  package=\$(python3 -c 'import pathlib, lightrag; print(pathlib.Path(lightrag.__file__).resolve().parent)')
  routers=\$package/api/routers
  test -f \$routers/query_routes.py
  test -f \$routers/document_routes.py
  mkdir -p '$BOARD_DATA_ROOT/extensions'
  cp '$EXT_ROOT/selective_ingest_router.py' \$routers/selective_ingest_router.py
  python3 '$EXT_ROOT/install_lightrag_upload_hook.py' \$routers/document_routes.py
  python3 '$EXT_ROOT/install_lightrag_document_grouping_hook.py' \$routers/document_routes.py
  python3 '$EXT_ROOT/install_lightrag_query_gate_hook.py' \$routers/query_routes.py
  python3 '$EXT_ROOT/install_lightrag_queue_progress_hook.py' \$routers/query_routes.py
  webui=\$(find \$package -type f -name index.html -path '*webui*' -print -quit)
  test -n \"\$webui\"
  python3 '$EXT_ROOT/install_lightrag_query_status_banner.py' \"\$(dirname \"\$webui\")\" '$EXT_ROOT/webui/query-status-banner.js'
"

if [[ "$PARSER_MODE" == "rkvision" ]]; then
  adb -s "$ADB_SERIAL" shell "python3 -m pip install --disable-pip-version-check --upgrade -e '$BOARD_APP_ROOT/core/rkvision-parser'"
fi

echo "LightRAG extensions and '$PARSER_MODE' PDF parser integration installed on $ADB_SERIAL"
