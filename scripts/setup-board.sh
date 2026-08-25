#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PDF_PARSER_MODE="rkvision"
VERIFY=false

usage() {
  cat <<'EOF'
Usage: bash scripts/setup-board.sh [--pdf-parser cloud|rkvision] [--verify]

Complete x86-host deployment entry point:
  1. builds and deploys the RK1828 Qwen3.5-9B and vector services;
  2. deploys the RKLightRAG core and optional local PDF sidecar;
  3. installs pinned official LightRAG, applies hooks and starts the WebUI.

Prerequisites:
  - deploy/board.env and deploy/lightrag.env have been created;
  - RKNN3_MODEL_ZOO_ROOT, RK1828_C_COMPILER and RK1828_CXX_COMPILER are set;
  - rkvision additionally needs RK3588_SDK_ROOT, PDFIUM_ROOT,
    RK_VISION_PPOCR_SERVICE_ROOT and RK_VISION_DOCLAYOUT_SERVICE_ROOT;
  - cloud additionally needs MINERU_API_TOKEN in deploy/lightrag.env.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pdf-parser)
      [[ $# -ge 2 ]] || { echo "--pdf-parser requires cloud or rkvision" >&2; exit 2; }
      PDF_PARSER_MODE="$2"
      shift 2 ;;
    --verify) VERIFY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$PDF_PARSER_MODE" in cloud|rkvision) ;; *) echo "Invalid PDF parser mode: $PDF_PARSER_MODE" >&2; exit 2 ;; esac

[[ -f "$ROOT/deploy/board.env" ]] || { echo "Missing deploy/board.env" >&2; exit 1; }
[[ -f "$ROOT/deploy/lightrag.env" ]] || { echo "Missing deploy/lightrag.env" >&2; exit 1; }

model_args=()
[[ "$VERIFY" == true ]] && model_args+=(--verify)

bash "$ROOT/scripts/setup-model-services.sh" "${model_args[@]}"
bash "$ROOT/scripts/deploy-lightrag.sh" --pdf-parser "$PDF_PARSER_MODE"
