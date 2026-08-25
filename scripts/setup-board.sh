#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/internal/common.sh"
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
  - RKNN3_MODEL_ZOO_ROOT is set and the aarch64 compiler prefix is available
    (GCC_COMPILER defaults to aarch64-linux-gnu);
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

[[ -f "$ROOT/deploy/board.env" ]] || { error "Missing configuration file: deploy/board.env"; hint "cp deploy/board.env.example deploy/board.env"; exit 1; }
[[ -f "$ROOT/deploy/lightrag.env" ]] || { error "Missing configuration file: deploy/lightrag.env"; hint "cp deploy/lightrag.env.example deploy/lightrag.env"; exit 1; }

model_args=()
[[ "$VERIFY" == true ]] && model_args+=(--verify)

step "Set up RK1828 model services"
bash "$ROOT/scripts/setup-model-services.sh" "${model_args[@]}"
step "Deploy LightRAG and WebUI"
bash "$ROOT/scripts/deploy-lightrag.sh" --pdf-parser "$PDF_PARSER_MODE"
success "Full board setup completed."
