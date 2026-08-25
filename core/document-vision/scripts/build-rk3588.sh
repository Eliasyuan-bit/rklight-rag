#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sdk_root="${RK3588_SDK_ROOT:-}"
pdfium_root="${PDFIUM_ROOT:-}"
ppocr_service_root="${PPOCR_SERVICE_ROOT:-}"
doclayout_service_root="${DOCLAYOUT_SERVICE_ROOT:-}"
build_dir="${BUILD_DIR:-$repo_root/build-rk3588}"
stage_dir="${STAGE_DIR:-$repo_root/dist/rk3588}"
[[ -n "$sdk_root" ]] || { echo "error: set RK3588_SDK_ROOT" >&2; exit 2; }
[[ -n "$pdfium_root" ]] || { echo "error: set PDFIUM_ROOT to an aarch64 PDFium distribution" >&2; exit 2; }
[[ -n "$ppocr_service_root" ]] || { echo "error: set PPOCR_SERVICE_ROOT" >&2; exit 2; }
[[ -n "$doclayout_service_root" ]] || { echo "error: set DOCLAYOUT_SERVICE_ROOT" >&2; exit 2; }

cmake -S "$repo_root/native" -B "$build_dir" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_TOOLCHAIN_FILE="$repo_root/native/cmake/toolchains/rk3588-aarch64.cmake" \
  -DRK3588_SDK_ROOT="$sdk_root" \
  -DPDFIUM_ROOT="$pdfium_root" \
  -DPPOCR_SERVICE_ROOT="$ppocr_service_root" \
  -DDOCLAYOUT_SERVICE_ROOT="$doclayout_service_root" \
  -DCMAKE_INSTALL_PREFIX="$stage_dir"
cmake --build "$build_dir" -j"$(nproc)"
rm -rf "$stage_dir"
cmake --install "$build_dir"
file "$stage_dir/bin/pdf_page_parse" | grep -q aarch64
echo "RK3588 package: $stage_dir"
