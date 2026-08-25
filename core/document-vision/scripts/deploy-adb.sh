#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
stage_dir="${STAGE_DIR:-$repo_root/dist/rk3588}"
target_root="${TARGET_ROOT:-/userdata/document-vision-service}"
adb_args=()
if [[ -n "${ADB_SERIAL:-}" ]]; then
  adb_args=(-s "$ADB_SERIAL")
fi

[[ -x "$stage_dir/bin/pdf_page_parse" ]] || {
  echo "error: build the RK3588 package first: $stage_dir/bin/pdf_page_parse is missing" >&2
  exit 2
}

adb "${adb_args[@]}" shell "mkdir -p '$target_root/bin' '$target_root/lib' '$target_root/input' '$target_root/output'"
adb "${adb_args[@]}" push "$stage_dir/bin/." "$target_root/bin/"
adb "${adb_args[@]}" push "$stage_dir/lib/." "$target_root/lib/"
adb "${adb_args[@]}" shell "chmod 755 '$target_root/bin/'*"
echo "deployed: $target_root"
