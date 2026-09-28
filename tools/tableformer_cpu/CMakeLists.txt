cmake_minimum_required(VERSION 3.16)
project(tableformer_cpu LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(ORT_ROOT "" CACHE PATH "ONNX Runtime ARM64 SDK root")
if(NOT ORT_ROOT)
  message(FATAL_ERROR "Set ORT_ROOT to the ARM64 ONNX Runtime SDK")
endif()

add_library(onnxruntime SHARED IMPORTED)
set_target_properties(onnxruntime PROPERTIES
  IMPORTED_LOCATION "${ORT_ROOT}/lib/aarch64/libonnxruntime.so.1.26.0"
  INTERFACE_INCLUDE_DIRECTORIES "${ORT_ROOT}/include")

add_executable(tableformer_cpu src/main.cc)
target_include_directories(tableformer_cpu PRIVATE third_party third_party/stb)
target_link_libraries(tableformer_cpu PRIVATE onnxruntime pthread dl)
target_compile_options(tableformer_cpu PRIVATE -O2 -Wall -Wextra)
set_target_properties(tableformer_cpu PROPERTIES
  BUILD_RPATH "\$ORIGIN/lib"
  INSTALL_RPATH "\$ORIGIN/lib")

install(TARGETS tableformer_cpu RUNTIME DESTINATION .)
install(FILES "${ORT_ROOT}/lib/aarch64/libonnxruntime.so.1.26.0" DESTINATION lib)
install(CODE "execute_process(COMMAND \"${CMAKE_COMMAND}\" -E create_symlink libonnxruntime.so.1.26.0 \"$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/libonnxruntime.so.1\")")
install(CODE "execute_process(COMMAND \"${CMAKE_COMMAND}\" -E create_symlink libonnxruntime.so.1.26.0 \"$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/libonnxruntime.so\")")
install(PROGRAMS
  scripts/run.sh
  scripts/run_pdf.sh
  scripts/pdf_table_parse.py
  DESTINATION .)
