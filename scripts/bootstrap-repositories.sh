#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

git submodule sync --recursive
git submodule update --init --recursive

echo "Checked out registered model service repositories."
echo "The official LightRAG source is installed separately by the board deployment step."
