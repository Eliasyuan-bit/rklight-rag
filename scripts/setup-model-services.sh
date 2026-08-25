#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/internal/common.sh"
VERIFY=false

usage() {
  cat <<'EOF'
Usage: bash scripts/setup-model-services.sh [--verify]

Builds and packages the Qwen3.5-9B and Qwen3 Embedding/Reranker services on
the current x86 host, then deploys their binaries, libraries and JSON configs
to the board selected in deploy/board.env. Model weight files are not copied.

Required environment variables:
  RKNN3_MODEL_ZOO_ROOT  path to rknn3-model-zoo
  GCC_COMPILER          path to the aarch64 GCC executable

Optional overrides:
  RK1828_C_COMPILER     full path to the aarch64 C compiler
  RK1828_CXX_COMPILER   full path to the aarch64 C++ compiler
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify) VERIFY=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

[[ -f "$ROOT/deploy/board.env" ]] || {
  error "Missing configuration file: $ROOT/deploy/board.env"
  hint "cp deploy/board.env.example deploy/board.env"
  exit 1
}
# shellcheck disable=SC1091
source "$ROOT/deploy/board.env"

[[ -n "${ADB_SERIAL:-}" ]] || { error "ADB_SERIAL is not set in deploy/board.env."; exit 1; }
command -v adb >/dev/null || { error "adb was not found in PATH."; exit 1; }
adb -s "$ADB_SERIAL" get-state >/dev/null || { error "Cannot connect to ADB device: $ADB_SERIAL"; exit 1; }

step "Build and package model services"
bash "$ROOT/scripts/internal/build-model-services.sh"

step "Deploy Qwen3.5-9B service to $ADB_SERIAL"
ADB_SERIAL="$ADB_SERIAL" \
  bash "$ROOT/components/RK1828-qwen3.5-9b-2cards-service/scripts/deploy-adb.sh"

step "Deploy Embedding/Reranker service to $ADB_SERIAL"
bash "$ROOT/components/RK1828-qwen3-embedding-reranker-service/scripts/deploy-adb.sh" "$ADB_SERIAL"

if [[ "$VERIFY" == true ]]; then
  step "Verify vector service deployment"
  bash "$ROOT/components/RK1828-qwen3-embedding-reranker-service/scripts/verify-adb.sh" "$ADB_SERIAL"
  step "Verify Qwen3.5-9B service (initializes the two-card model)"
  ADB_SERIAL="$ADB_SERIAL" \
    bash "$ROOT/components/RK1828-qwen3.5-9b-2cards-service/scripts/verify-adb.sh"
fi

success "Model service build and deployment completed for $ADB_SERIAL."
