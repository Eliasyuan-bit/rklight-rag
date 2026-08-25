#!/usr/bin/env bash
# Deploy the RKLightRAG orchestration layer to a prepared board.
# Model-service binaries and model assets are intentionally not built here.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WITH_DOCUMENT_VISION=false
CLI_PDF_PARSER_MODE=""

usage() {
  cat <<'EOF'
Usage: bash scripts/deploy-lightrag.sh [--pdf-parser cloud|rkvision]

Installs the RKLightRAG orchestration layer in this order:
  1. initialise pinned model-service submodules
  2. validate local board configuration and ADB connectivity
  3. deploy gateway, routing and LightRAG extension sources
  4. use either official MinerU cloud parsing or local RKVision parsing
  5. fetch the pinned upstream LightRAG source and install extensions
  6. start the gateway and LightRAG, then run health checks

Prerequisites:
  - deploy/board.env and deploy/lightrag.env have been created from examples;
  - four model services, their model assets, and their runtime libraries have
    already been built and deployed to the paths in deploy/board.env;
  - --pdf-parser rkvision needs the host-side toolchain and PDFium variables
    required by scripts/internal/build-document-vision.sh;
  - --pdf-parser cloud needs MINERU_API_TOKEN in deploy/lightrag.env.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pdf-parser)
      [[ $# -ge 2 ]] || { echo "--pdf-parser requires cloud or rkvision" >&2; exit 2; }
      CLI_PDF_PARSER_MODE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -f "$ROOT_DIR/deploy/board.env" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/deploy/board.env"
fi
PDF_PARSER_MODE="${CLI_PDF_PARSER_MODE:-${PDF_PARSER_MODE:-cloud}}"
case "$PDF_PARSER_MODE" in
  cloud) ;;
  rkvision) WITH_DOCUMENT_VISION=true ;;
  *) echo "PDF parser mode must be cloud or rkvision" >&2; exit 2 ;;
esac
export RK_PDF_PARSER_MODE="$PDF_PARSER_MODE"

run_step() {
  local label="$1"
  shift
  printf '\n==> %s\n' "$label"
  "$@"
}

cd "$ROOT_DIR"
run_step "Initialise pinned repositories" bash ./scripts/internal/bootstrap-repositories.sh
run_step "Validate board configuration" bash ./scripts/internal/check-config.sh
run_step "Deploy RKLightRAG core" bash ./scripts/internal/deploy-board.sh

if "$WITH_DOCUMENT_VISION"; then
  run_step "Build document-vision sidecar" bash ./scripts/internal/build-document-vision.sh
  run_step "Deploy document-vision sidecar" bash ./scripts/internal/deploy-document-vision.sh
fi

run_step "Fetch pinned upstream LightRAG" bash ./scripts/internal/install-lightrag-upstream.sh
run_step "Install LightRAG extensions" bash ./scripts/internal/install-lightrag-extensions.sh
run_step "Start services" bash ./scripts/internal/start-board.sh
run_step "Verify deployment" bash ./scripts/internal/verify-board.sh

printf '\nRKLightRAG deployment completed.\n'
