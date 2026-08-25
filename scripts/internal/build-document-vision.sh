#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$BASH_SOURCE")/../.." && pwd)"

test -n "$RK3588_SDK_ROOT"
test -n "$PDFIUM_ROOT"
test -n "${RK_VISION_PPOCR_SERVICE_ROOT:-}"
test -n "${RK_VISION_DOCLAYOUT_SERVICE_ROOT:-}"

export PPOCR_SERVICE_ROOT="$RK_VISION_PPOCR_SERVICE_ROOT"
export DOCLAYOUT_SERVICE_ROOT="$RK_VISION_DOCLAYOUT_SERVICE_ROOT"
export RK3588_SDK_ROOT PDFIUM_ROOT PPOCR_SERVICE_ROOT DOCLAYOUT_SERVICE_ROOT
exec bash "$ROOT/core/document-vision/scripts/build-rk3588.sh"
