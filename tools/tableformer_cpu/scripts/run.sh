#!/usr/bin/env bash
set -euo pipefail

base_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
image=${1:?"usage: ./run.sh IMAGE [OUTPUT.md] [MAX_STEPS]"}
output=${2:-"${base_dir}/table.md"}
max_steps=${3:-256}

exec "${base_dir}/tableformer_cpu" \
  "${image}" "${output}" \
  "${base_dir}/models/encoder.onnx" \
  "${base_dir}/models/decoder.onnx" \
  "${base_dir}/models/bbox.onnx" \
  "${max_steps}"
