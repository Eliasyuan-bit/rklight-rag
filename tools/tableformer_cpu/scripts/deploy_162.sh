#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
package_dir=${PACKAGE_DIR:-"${project_dir}/out/tableformer_cpu"}
host_162=${HOST_162:-rockchip-yn@172.16.15.162}
adb_serial=${ADB_SERIAL:-32a331f9ae73952d}
remote_dir=${REMOTE_DIR:-/userdata/tableformer_cpu}
model_dir=${MODEL_DIR_162:-/home/rockchip-yn/data/rknn_model_zoo-main/examples/table_former/models}

test -x "${package_dir}/tableformer_cpu"
ssh "${host_162}" "rm -rf /tmp/tableformer_cpu_package"
scp -O -qr "${package_dir}" "${host_162}:/tmp/tableformer_cpu_package"
ssh "${host_162}" "adb -s '${adb_serial}' shell 'mkdir -p ${remote_dir}/models' && \
  adb -s '${adb_serial}' push /tmp/tableformer_cpu_package/. '${remote_dir}/' >/dev/null && \
  adb -s '${adb_serial}' push '${model_dir}/encoder.onnx' '${model_dir}/decoder.onnx' '${model_dir}/decoder.onnx.data' '${model_dir}/bbox.onnx' '${model_dir}/bbox.onnx.data' '${remote_dir}/models/' >/dev/null && \
  adb -s '${adb_serial}' shell 'chmod +x ${remote_dir}/tableformer_cpu ${remote_dir}/run.sh'"
echo "Deployed to ${remote_dir} on ${adb_serial}"
