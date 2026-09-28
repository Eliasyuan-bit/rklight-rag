#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
build_dir=${BUILD_DIR:-"${project_dir}/out/build-aarch64"}
install_dir=${INSTALL_DIR:-"${project_dir}/out/tableformer_cpu"}
ort_root=${ORT_ROOT:-/home/yn/gan/codeformer_3588/third_party/onnxruntime}

cmake -S "${project_dir}" -B "${build_dir}" \
  -DCMAKE_TOOLCHAIN_FILE="${project_dir}/cmake/aarch64-linux-gnu.cmake" \
  -DORT_ROOT="${ort_root}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="${install_dir}"
cmake --build "${build_dir}" --parallel
cmake --install "${build_dir}"
convert -background white "${project_dir}/testdata/simple_table.svg" \
  "${project_dir}/testdata/simple_table.png"
file "${install_dir}/tableformer_cpu"
echo "Package: ${install_dir}"
