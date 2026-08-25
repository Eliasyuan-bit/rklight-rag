#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

PDFIUM_ROOT_EXPLICIT="${PDFIUM_ROOT:-}"
PDFIUM_ROOT="${PDFIUM_ROOT_EXPLICIT:-$ROOT/third_party/pdfium/linux-arm64}"
PDFIUM_URL="${PDFIUM_URL:-https://github.com/bblanchon/pdfium-binaries/releases/latest/download/pdfium-linux-arm64.tgz}"

if [[ -f "$PDFIUM_ROOT/include/fpdfview.h" && -e "$PDFIUM_ROOT/lib/libpdfium.so" ]]; then
  success "Using cached PDFium: $PDFIUM_ROOT"
  exit 0
fi

if [[ -n "$PDFIUM_ROOT_EXPLICIT" ]]; then
  error "PDFIUM_ROOT is set but does not contain a valid aarch64 PDFium package: $PDFIUM_ROOT"
  hint "Unset PDFIUM_ROOT to download the managed PDFium package automatically."
  exit 1
fi

command -v curl >/dev/null || { error "curl is required to download PDFium."; exit 1; }
command -v tar >/dev/null || { error "tar is required to unpack PDFium."; exit 1; }

step "Downloading aarch64 PDFium"
warning "Source: $PDFIUM_URL"

work_dir="$(mktemp -d)"
cleanup() { rm -rf "$work_dir"; }
trap cleanup EXIT

archive="$work_dir/pdfium-linux-arm64.tgz"
curl --fail --location --retry 3 --output "$archive" "$PDFIUM_URL"
mkdir -p "$work_dir/unpacked"
tar -xzf "$archive" -C "$work_dir/unpacked"

pdfium_include="$(find "$work_dir/unpacked" -type f -path '*/include/fpdfview.h' -print -quit)"
[[ -n "$pdfium_include" ]] || { error "Downloaded archive does not contain include/fpdfview.h."; exit 1; }
payload_root="$(dirname "$(dirname "$pdfium_include")")"
[[ -e "$payload_root/lib/libpdfium.so" ]] || { error "Downloaded archive does not contain lib/libpdfium.so."; exit 1; }

mkdir -p "$(dirname "$PDFIUM_ROOT")"
mv "$payload_root" "$PDFIUM_ROOT"
success "PDFium is ready: $PDFIUM_ROOT"
