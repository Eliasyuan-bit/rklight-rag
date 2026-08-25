#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERIFY=false

usage() {
  cat <<'EOF'
Usage: bash scripts/build-deploy-model-services.sh [--verify]

Builds and packages the Qwen3.5-9B and Qwen3 Embedding/Reranker services on
the current x86 host, then deploys their binaries, libraries and JSON configs
to the board selected in deploy/board.env. Model weight files are not copied.

Required environment variables:
  RKNN3_MODEL_ZOO_ROOT  path to rknn3-model-zoo
  RK1828_C_COMPILER     aarch64 C compiler
  RK1828_CXX_COMPILER   aarch64 C++ compiler
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
  echo "Missing $ROOT/deploy/board.env; copy deploy/board.env.example first." >&2
  exit 1
}
# shellcheck disable=SC1091
source "$ROOT/deploy/board.env"

[[ -n "${ADB_SERIAL:-}" ]] || { echo "ADB_SERIAL is not set in deploy/board.env." >&2; exit 1; }
command -v adb >/dev/null || { echo "adb is required." >&2; exit 1; }
adb -s "$ADB_SERIAL" get-state >/dev/null

echo "==> Build and package model services"
bash "$ROOT/scripts/build-model-services.sh"

echo "==> Deploy Qwen3.5-9B service to $ADB_SERIAL"
ADB_SERIAL="$ADB_SERIAL" \
  bash "$ROOT/components/RK1828-qwen3.5-9b-2cards-service/scripts/deploy-adb.sh"

echo "==> Deploy Embedding/Reranker service to $ADB_SERIAL"
bash "$ROOT/components/RK1828-qwen3-embedding-reranker-service/scripts/deploy-adb.sh" "$ADB_SERIAL"

if [[ "$VERIFY" == true ]]; then
  echo "==> Verify vector service deployment"
  bash "$ROOT/components/RK1828-qwen3-embedding-reranker-service/scripts/verify-adb.sh" "$ADB_SERIAL"
  echo "==> Verify Qwen3.5-9B service (initializes the two-card model)"
  ADB_SERIAL="$ADB_SERIAL" \
    bash "$ROOT/components/RK1828-qwen3.5-9b-2cards-service/scripts/verify-adb.sh"
fi

echo "Model service build and deployment completed for $ADB_SERIAL."
