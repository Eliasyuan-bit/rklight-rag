#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if [[ -z "${RK1828_C_COMPILER:-}" && -n "${GCC_COMPILER:-}" ]]; then
  RK1828_C_COMPILER="$GCC_COMPILER"
fi
if [[ -z "${RK1828_C_COMPILER:-}" ]]; then
  RK1828_C_COMPILER="$(command -v aarch64-linux-gnu-gcc 2>/dev/null || true)"
fi
if [[ -z "${RK1828_CXX_COMPILER:-}" && -n "$RK1828_C_COMPILER" ]]; then
  RK1828_CXX_COMPILER="${RK1828_C_COMPILER%gcc}g++"
fi

BUILD_ENV_INVALID=false
if [[ -z "${RKNN3_MODEL_ZOO_ROOT:-}" ]]; then
  error "Missing required environment variable: RKNN3_MODEL_ZOO_ROOT"
  BUILD_ENV_INVALID=true
fi
if [[ -z "$RK1828_C_COMPILER" || -z "$RK1828_CXX_COMPILER" ]]; then
  error "Cannot determine the aarch64 GCC/G++ toolchain."
  BUILD_ENV_INVALID=true
fi

if [[ "$BUILD_ENV_INVALID" == true ]]; then
  hint "Run the following on the x86 build host:"
  hint "export RKNN3_MODEL_ZOO_ROOT=/home/yn/sdk/182x/rknn/rknn3-model-zoo"
  hint "export GCC_COMPILER=<path-to-aarch64-gcc>"
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
