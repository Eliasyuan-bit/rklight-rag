#!/usr/bin/env bash
# Run on the machine holding a completed current-board snapshot.
set -euo pipefail

snapshot=${1:?Usage: manifest-snapshot.sh SNAPSHOT_DIR}
snapshot=$(realpath "$snapshot")
case "$snapshot" in /tmp|/tmp/*) echo "Refusing /tmp snapshot" >&2; exit 2 ;; esac
test -d "$snapshot/userdata/rklight-rag"
test ! -e "$snapshot/userdata/lightrag-data" || {
  echo "Knowledge-base data must not be included in this snapshot" >&2
  exit 1
}

export TMPDIR="$snapshot/.work"
export TMP="$TMPDIR" TEMP="$TMPDIR"
mkdir -p "$TMPDIR"

(
  cd "$snapshot"
  find . -path './.work' -prune -o -type f ! -name SHA256SUMS ! -name SHA256SUMS.next -print0 \
    | LC_ALL=C sort -z \
    | xargs -0 -r sha256sum > SHA256SUMS.next
  mv SHA256SUMS.next SHA256SUMS
)
echo "Manifest created: $snapshot/SHA256SUMS"
