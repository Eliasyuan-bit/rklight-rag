#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$BASH_SOURCE")/../.." && pwd)"
bash "$ROOT/scripts/internal/check-config.sh"
source "$ROOT/deploy/board.env"

PARSER_MODE="${RK_PDF_PARSER_MODE:-${PDF_PARSER_MODE:-cloud}}"
case "$PARSER_MODE" in cloud|rkvision) ;; *) echo "PDF parser mode must be cloud or rkvision, got: $PARSER_MODE" >&2; exit 2 ;; esac

EXT_ROOT="$BOARD_APP_ROOT/core/lightrag-extensions"
PYTHON="$BOARD_APP_ROOT/venv/bin/python"
adb -s "$ADB_SERIAL" shell "
  set -e
  PATH='$BOARD_APP_ROOT/venv/bin':\$PATH
  export PATH
  test -x '$PYTHON'
  package=\$('$PYTHON' -c 'import pathlib, lightrag; assert lightrag.__file__; print(pathlib.Path(lightrag.__file__).resolve().parent)') || exit 1
  test -n \"\$package\"
  routers=\$package/api/routers
  test -f \$routers/query_routes.py
  test -f \$routers/document_routes.py
  mkdir -p '$BOARD_DATA_ROOT/extensions'
  cp '$EXT_ROOT/rk_lexical_retrieval.py' \$package/rk_lexical_retrieval.py
  cp '$EXT_ROOT/rk_chunk_citations.py' \$package/rk_chunk_citations.py
  cp '$EXT_ROOT/rk_chunk_budget.py' \$package/rk_chunk_budget.py
  cp '$EXT_ROOT/rk_source_policy.py' \$package/rk_source_policy.py
  cp '$EXT_ROOT/rk_table_parent.py' \$package/rk_table_parent.py
  cp '$EXT_ROOT/rk_evidence_refiner.py' \$package/rk_evidence_refiner.py
  cp '$EXT_ROOT/rk_section_parent.py' \$package/rk_section_parent.py
  cp '$EXT_ROOT/rk_reference_markdown.py' \$package/rk_reference_markdown.py
  cp '$EXT_ROOT/rk_reference_preview.py' \$package/rk_reference_preview.py
  cp '$EXT_ROOT/rk_ingest_model_mode.py' \$package/rk_ingest_model_mode.py
  cp '$EXT_ROOT/rk_paged_extraction.py' \$package/rk_paged_extraction.py
  cp '$EXT_ROOT/selective_ingest_router.py' \$routers/selective_ingest_router.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_upload_hook.py' \$routers/document_routes.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_document_grouping_hook.py' \$routers/document_routes.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_query_gate_hook.py' \$routers/query_routes.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_queue_progress_hook.py' \$routers/query_routes.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_query_default_hook.py' \$routers/query_routes.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_query_prompt_normalization_hook.py' \$routers/query_routes.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_lexical_retrieval_hook.py' \$package/operate.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_focused_merge_hook.py' \$package/operate.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_paged_extraction_hook.py' \$package/operate.py \$package/prompt.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_retrieval_trace_hook.py' \$package/utils.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_source_policy_hook.py' \$package/utils.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_relation_context_hook.py' \$package/operate.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_user_prompt_fallback_hook.py' \$package/operate.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_chunk_citation_hook.py' \$package/utils.py \$routers/query_routes.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_reference_location_hook.py' \$routers/query_routes.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_reference_footer_hook.py' \$routers/query_routes.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_reference_preview_hook.py' \$routers/query_routes.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_reference_group_hook.py' \$routers/query_routes.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_document_reference_footer_hook.py' \$routers/query_routes.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_chunk_budget_hook.py' \$package/utils.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_answer_cache_version_hook.py' \$package/operate.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_ingest_model_mode_hook.py' \$package/pipeline.py
  '$PYTHON' '$EXT_ROOT/install_lightrag_model_transition_status_hook.py' \$routers/document_routes.py \$package/api/lightrag_server.py
  if test -f '$BOARD_DATA_ROOT/kv_store_text_chunks.json'; then
    '$PYTHON' '$EXT_ROOT/build_table_parent_index.py' '$BOARD_DATA_ROOT/kv_store_text_chunks.json' '$BOARD_DATA_ROOT/table_parent_index.json' --parsed-root '$BOARD_DATA_ROOT/inputs/__parsed__'
  fi
  webui=\$package/api/webui/index.html
  test -f \"\$webui\"
  python3 '$EXT_ROOT/install_lightrag_query_status_banner.py' \"\$(dirname \"\$webui\")\" '$EXT_ROOT/webui/query-status-banner.js'
  python3 '$EXT_ROOT/install_lightrag_reference_reader.py' \"\$(dirname \"\$webui\")\" '$EXT_ROOT/webui/reference-reader.js'
"

if [[ "$PARSER_MODE" == "rkvision" ]]; then
  adb -s "$ADB_SERIAL" shell "'$PYTHON' -m pip install --disable-pip-version-check --no-deps --no-build-isolation --upgrade -e '$BOARD_APP_ROOT/core/rkvision-parser'"
fi

echo "LightRAG extensions and '$PARSER_MODE' PDF parser integration installed on $ADB_SERIAL"
