#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if ! require_variables RKNN3_MODEL_ZOO_ROOT RK1828_C_COMPILER RK1828_CXX_COMPILER; then
  hint "在当前 x86 开发机执行："
  hint "export RKNN3_MODEL_ZOO_ROOT=/home/yn/sdk/182x/rknn/rknn3-model-zoo"
  hint "export RK1828_C_COMPILER=/usr/bin/aarch64-linux-gnu-gcc"
  hint "export RK1828_CXX_COMPILER=/usr/bin/aarch64-linux-gnu-g++"
  exit 2
fi

[[ -d "$RKNN3_MODEL_ZOO_ROOT" ]] || { error "RKNN3_MODEL_ZOO_ROOT 不存在：$RKNN3_MODEL_ZOO_ROOT"; exit 2; }
[[ -x "$RK1828_C_COMPILER" ]] || { error "RK1828_C_COMPILER 不可执行：$RK1828_C_COMPILER"; exit 2; }
[[ -x "$RK1828_CXX_COMPILER" ]] || { error "RK1828_CXX_COMPILER 不可执行：$RK1828_CXX_COMPILER"; exit 2; }

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
