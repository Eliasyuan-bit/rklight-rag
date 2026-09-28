#!/usr/bin/env bash
set -euo pipefail

base_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export TF_TABLEFORMER_ROOT=${TF_TABLEFORMER_ROOT:-"${base_dir}"}

exec python3 "${base_dir}/pdf_table_parse.py" "$@"
