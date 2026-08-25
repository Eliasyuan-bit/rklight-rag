#!/usr/bin/env bash
# Start an already deployed RKLightRAG board without rebuilding or reinstalling.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/internal/common.sh"

step "Start deployed services"
bash "$ROOT/scripts/internal/start-board.sh"
step "Verify deployed services"
bash "$ROOT/scripts/internal/verify-board.sh"
success "RKLightRAG is ready."
