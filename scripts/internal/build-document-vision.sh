#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$BASH_SOURCE")/../.." && pwd)"
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if ! require_variables RK3588_SDK_ROOT PDFIUM_ROOT RK_VISION_PPOCR_SERVICE_ROOT RK_VISION_DOCLAYOUT_SERVICE_ROOT; then
  hint "RKVision requires RK3588 SDK, aarch64 PDFium, and host-side PPOCR/Layout build directories."
  hint "See 'Local RKVision PDF sidecar build variables' in docs/environment.md."
  exit 2
fi

export PPOCR_SERVICE_ROOT="$RK_VISION_PPOCR_SERVICE_ROOT"
export DOCLAYOUT_SERVICE_ROOT="$RK_VISION_DOCLAYOUT_SERVICE_ROOT"
export RK3588_SDK_ROOT PDFIUM_ROOT PPOCR_SERVICE_ROOT DOCLAYOUT_SERVICE_ROOT
exec bash "$ROOT/core/document-vision/scripts/build-rk3588.sh"
