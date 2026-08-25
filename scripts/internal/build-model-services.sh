#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if ! require_variables RKNN3_MODEL_ZOO_ROOT RK1828_C_COMPILER RK1828_CXX_COMPILER; then
  hint "Run the following on the x86 build host:"
  hint "export RKNN3_MODEL_ZOO_ROOT=/home/yn/sdk/182x/rknn/rknn3-model-zoo"
  hint "export RK1828_C_COMPILER=/usr/bin/aarch64-linux-gnu-gcc"
  hint "export RK1828_CXX_COMPILER=/usr/bin/aarch64-linux-gnu-g++"
  exit 2
fi

[[ -d "$RKNN3_MODEL_ZOO_ROOT" ]] || { error "RKNN3_MODEL_ZOO_ROOT does not exist: $RKNN3_MODEL_ZOO_ROOT"; exit 2; }
[[ -x "$RK1828_C_COMPILER" ]] || { error "RK1828_C_COMPILER is not executable: $RK1828_C_COMPILER"; exit 2; }
[[ -x "$RK1828_CXX_COMPILER" ]] || { error "RK1828_CXX_COMPILER is not executable: $RK1828_CXX_COMPILER"; exit 2; }

build_and_package() {
  local service_dir="$1"
  step "Building $(basename "$service_dir")"
  (
    cd "$service_dir"
    export RKNN3_MODEL_ZOO_ROOT RK1828_C_COMPILER RK1828_CXX_COMPILER
    bash scripts/build-rk1828.sh
    bash scripts/package-rk1828.sh
  )
}

build_and_package "$ROOT/components/RK1828-qwen3.5-9b-2cards-service"
build_and_package "$ROOT/components/RK1828-qwen3-embedding-reranker-service"

success "Model service packages are ready."
printf '  %s\n' "$ROOT/components/RK1828-qwen3.5-9b-2cards-service/dist/RK1828-qwen3.5-9b-2cards-service"
printf '  %s\n' "$ROOT/components/RK1828-qwen3-embedding-reranker-service/dist/RK1828-qwen3-embedding-reranker-service"
