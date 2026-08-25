#!/usr/bin/env bash
set -euo pipefail

# Creates a redistributable PDFIUM_ROOT from a pinned arm64 pypdfium2 wheel
# (which packages libpdfium.so) and the matching public C headers source.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_root="${1:-$repo_root/third_party/pdfium}"
wheel_version="${PDFIUM_PYPDFIUM2_VERSION:-5.13.0}"
headers_repo="${PDFIUM_HEADERS_REPOSITORY:-https://github.com/chromium/pdfium.git}"
work_dir="${output_root}.work"

rm -rf "$work_dir"
mkdir -p "$work_dir/wheels" "$output_root/include" "$output_root/lib" "$output_root/licenses"
python3 -m pip download --only-binary=:all: --platform manylinux2014_aarch64 \
  --implementation cp --python-version 310 --abi cp310 --no-deps \
  -d "$work_dir/wheels" "pypdfium2==$wheel_version"
wheel_path="$(find "$work_dir/wheels" -name '*.whl' -print -quit)"
[[ -n "$wheel_path" ]] || { echo "error: arm64 pypdfium2 wheel was not downloaded" >&2; exit 1; }
unzip -q "$wheel_path" -d "$work_dir/wheel"

git clone --depth 1 --filter=blob:none --sparse "$headers_repo" "$work_dir/pdfium-headers"
git -C "$work_dir/pdfium-headers" sparse-checkout set public
cp -a "$work_dir/pdfium-headers/public/." "$output_root/include/"
cp "$work_dir/wheel/pypdfium2_raw/libpdfium.so" "$output_root/lib/libpdfium.so"
cp -a "$work_dir/wheel"/*dist-info/licenses/. "$output_root/licenses/"
printf 'pypdfium2=%s\n' "$wheel_version" > "$output_root/VERSION"
printf 'headers_repo=%s\n' "$headers_repo" >> "$output_root/VERSION"
echo "PDFIUM_ROOT prepared at: $output_root"
