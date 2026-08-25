#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$BASH_SOURCE")/../.." && pwd)"
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if [[ -z "${RK3588_SDK_ROOT:-}" && -n "${GCC_COMPILER:-}" ]]; then
  SDK_FROM_GCC="${GCC_COMPILER%%/prebuilts/gcc/*}"
  if [[ "$SDK_FROM_GCC" != "$GCC_COMPILER" && -d "$SDK_FROM_GCC/prebuilts" ]]; then
    RK3588_SDK_ROOT="$SDK_FROM_GCC"
    warning "Derived RK3588_SDK_ROOT from GCC_COMPILER: $RK3588_SDK_ROOT"
  fi
fi

if ! require_variables RK3588_SDK_ROOT PDFIUM_ROOT; then
  hint "RKVision requires an RK3588 SDK and aarch64 PDFium."
  [[ -n "${RK3588_SDK_ROOT:-}" ]] || hint "export RK3588_SDK_ROOT=<path-to-rk3588-sdk>"
  [[ -n "${PDFIUM_ROOT:-}" ]] || hint "export PDFIUM_ROOT=<path-to-aarch64-pdfium>"
  hint "PPOCR and DocLayout paths are resolved from components/ automatically."
  hint "See 'Local RKVision PDF sidecar build variables' in docs/environment.md."
  exit 2
fi

export PPOCR_SERVICE_ROOT="$ROOT/components/ppocrv6-rknn-service"
export DOCLAYOUT_SERVICE_ROOT="$ROOT/components/doclayout-yolo-rknn-service"
export RK3588_SDK_ROOT PDFIUM_ROOT PPOCR_SERVICE_ROOT DOCLAYOUT_SERVICE_ROOT
exec bash "$ROOT/core/document-vision/scripts/build-rk3588.sh"
