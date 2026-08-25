#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$BASH_SOURCE")/../.." && pwd)"
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if [[ -z "${PDFIUM_ROOT:-}" ]]; then
  bash "$ROOT/scripts/internal/prepare-pdfium.sh"
  PDFIUM_ROOT="$ROOT/third_party/pdfium/linux-arm64"
fi

if [[ -z "${RK3588_SDK_ROOT:-}" && -n "${GCC_COMPILER:-}" ]]; then
  SDK_FROM_GCC="${GCC_COMPILER%%/prebuilts/gcc/*}"
  if [[ "$SDK_FROM_GCC" != "$GCC_COMPILER" && -d "$SDK_FROM_GCC/prebuilts" ]]; then
    RK3588_SDK_ROOT="$SDK_FROM_GCC"
    warning "Derived RK3588_SDK_ROOT from GCC_COMPILER: $RK3588_SDK_ROOT"
  fi
fi

if ! require_variables RK3588_SDK_ROOT PDFIUM_ROOT; then
  hint "RKVision requires an RK3588 SDK. PDFium is downloaded automatically when PDFIUM_ROOT is unset."
  [[ -n "${RK3588_SDK_ROOT:-}" ]] || hint "export RK3588_SDK_ROOT=<path-to-rk3588-sdk>"
  [[ -n "${PDFIUM_ROOT:-}" ]] || hint "export PDFIUM_ROOT=<path-to-aarch64-pdfium>"
  hint "PPOCR and DocLayout paths are resolved from components/ automatically."
  hint "See 'Local RKVision PDF sidecar build variables' in docs/environment.md."
  exit 2
fi

export PPOCR_SERVICE_ROOT="$ROOT/components/ppocrv6-rknn-service"
export DOCLAYOUT_SERVICE_ROOT="$ROOT/components/doclayout-yolo-rknn-service"
export RK3588_SDK_ROOT PDFIUM_ROOT PPOCR_SERVICE_ROOT DOCLAYOUT_SERVICE_ROOT

if [[ ! -f "$PPOCR_SERVICE_ROOT/dist/rk3588/bin/libppocrv6_rknn_core.so" ]]; then
  step "Build PPOCRv6 RK3588 core"
  bash "$PPOCR_SERVICE_ROOT/scripts/build-rk3588.sh"
fi

if [[ ! -f "$DOCLAYOUT_SERVICE_ROOT/dist/rk3588/bin/libdoclayout_yolo_rknn_core.so" ]]; then
  step "Build DocLayout-YOLO RK3588 core"
  bash "$DOCLAYOUT_SERVICE_ROOT/scripts/build-rk3588.sh"
fi

success "PPOCRv6 and DocLayout-YOLO RK3588 cores are ready."
exec bash "$ROOT/core/document-vision/scripts/build-rk3588.sh"
