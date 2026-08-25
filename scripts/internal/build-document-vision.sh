#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$BASH_SOURCE")/../.." && pwd)"
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if ! require_variables RK3588_SDK_ROOT PDFIUM_ROOT RK_VISION_PPOCR_SERVICE_ROOT RK_VISION_DOCLAYOUT_SERVICE_ROOT; then
  hint "RKVision 需要 RK3588 SDK、aarch64 PDFium 与主机侧 PPOCR/Layout 服务构建目录。"
  hint "完整说明见 docs/environment.md 的“本地 RKVision PDF sidecar 的构建变量”。"
  exit 2
fi

export PPOCR_SERVICE_ROOT="$RK_VISION_PPOCR_SERVICE_ROOT"
export DOCLAYOUT_SERVICE_ROOT="$RK_VISION_DOCLAYOUT_SERVICE_ROOT"
export RK3588_SDK_ROOT PDFIUM_ROOT PPOCR_SERVICE_ROOT DOCLAYOUT_SERVICE_ROOT
exec bash "$ROOT/core/document-vision/scripts/build-rk3588.sh"
