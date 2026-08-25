#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

: "${RKNN3_MODEL_ZOO_ROOT:?Set RKNN3_MODEL_ZOO_ROOT to rknn3-model-zoo}"
: "${RK1828_C_COMPILER:?Set RK1828_C_COMPILER to the aarch64 C compiler}"
: "${RK1828_CXX_COMPILER:?Set RK1828_CXX_COMPILER to the aarch64 C++ compiler}"

build_and_package() {
  local service_dir="$1"
  echo "==> Building $(basename "$service_dir")"
  (
    cd "$service_dir"
    export RKNN3_MODEL_ZOO_ROOT RK1828_C_COMPILER RK1828_CXX_COMPILER
    bash scripts/build-rk1828.sh
    bash scripts/package-rk1828.sh
  )
}

build_and_package "$ROOT/components/RK1828-qwen3.5-9b-2cards-service"
build_and_package "$ROOT/components/RK1828-qwen3-embedding-reranker-service"

echo "Packages are ready:"
echo "  $ROOT/components/RK1828-qwen3.5-9b-2cards-service/dist/RK1828-qwen3.5-9b-2cards-service"
echo "  $ROOT/components/RK1828-qwen3-embedding-reranker-service/dist/RK1828-qwen3-embedding-reranker-service"
