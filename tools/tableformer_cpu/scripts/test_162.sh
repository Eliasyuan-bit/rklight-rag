#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
host_162=${HOST_162:-rockchip-yn@172.16.15.162}
adb_serial=${ADB_SERIAL:-32a331f9ae73952d}
remote_dir=${REMOTE_DIR:-/userdata/tableformer_cpu}
input=${1:-"${project_dir}/testdata/simple_table.png"}
max_steps=${2:-256}
stage_dir=${STAGE_DIR_162:-/home/rockchip-yn/data/rklight-rag-stage/tableformer_cpu}

if [[ ! -f "${input}" ]]; then
  echo "Input image not found: ${input}" >&2
  echo "Run scripts/build.sh first to generate the default PNG fixture." >&2
  exit 1
fi

ssh "${host_162}" "mkdir -p '${stage_dir}'"
scp -q "${input}" "${host_162}:${stage_dir}/tableformer_input.png"
ssh "${host_162}" "adb -s '${adb_serial}' push '${stage_dir}/tableformer_input.png' '${remote_dir}/input.png' >/dev/null && \
  adb -s '${adb_serial}' shell 'cd ${remote_dir} && ./run.sh ./input.png ./output.md ${max_steps}' && \
  adb -s '${adb_serial}' pull '${remote_dir}/output.md' '${stage_dir}/tableformer_output.md' >/dev/null"
scp -q "${host_162}:${stage_dir}/tableformer_output.md" "${project_dir}/out/output.md"
echo "Result: ${project_dir}/out/output.md"
