#!/usr/bin/env bash
# Prove that the pinned upstream commit plus the archived patch reproduces
# every tracked LightRAG source change currently running on the board.
set -euo pipefail

snapshot=$(realpath "${1:?Usage: verify-board-source-patch.sh SNAPSHOT_DIR}")
case "$snapshot" in /tmp|/tmp/*) echo "Refusing /tmp snapshot" >&2; exit 2 ;; esac
source_root="$snapshot/userdata/rklight-rag/third_party/LightRAG"
patch="$snapshot/deploy/patches/lightrag-7ecd8a0-board.patch"
test -d "$source_root/.git"
test -s "$patch"
test "$(git -C "$source_root" rev-parse HEAD)" = 7ecd8a0512c1f5b221456b24de225a71e1e002d8

mkdir -p "$snapshot/.work/tmp"
export TMPDIR="$snapshot/.work/tmp" TMP="$snapshot/.work/tmp" TEMP="$snapshot/.work/tmp"
replay=$(mktemp -d "$snapshot/.work/upstream-patch.XXXXXXXX")
git -C "$source_root" archive HEAD | tar -C "$replay" -xf -
git -C "$replay" apply --check "$patch"
git -C "$replay" apply "$patch"

count=0
while IFS= read -r path; do
  cmp "$replay/$path" "$source_root/$path" || {
    echo "Source mismatch: $path" >&2
    exit 1
  }
  count=$((count + 1))
done < <(git -C "$source_root" diff --name-only)
test "$count" -eq 9
echo "MATCH: pinned LightRAG plus patch reproduces all $count modified tracked files."
