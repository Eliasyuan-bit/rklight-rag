cmake_minimum_required(VERSION 3.16)
project(document_vision_service LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(NOT PDFIUM_ROOT)
  message(FATAL_ERROR "Set PDFIUM_ROOT to an aarch64 PDFium distribution root")
endif()
if(NOT PPOCR_SERVICE_ROOT)
  message(FATAL_ERROR "Set PPOCR_SERVICE_ROOT to the PPOCRv6 RKNN service source/build root")
endif()
if(NOT DOCLAYOUT_SERVICE_ROOT)
  message(FATAL_ERROR "Set DOCLAYOUT_SERVICE_ROOT to the DocLayout-YOLO RKNN service source/build root")
endif()
find_path(PDFIUM_INCLUDE_DIR fpdfview.h PATHS "${PDFIUM_ROOT}/include" "${PDFIUM_ROOT}/public" REQUIRED NO_CMAKE_FIND_ROOT_PATH)
find_library(PDFIUM_LIBRARY NAMES pdfium PATHS "${PDFIUM_ROOT}/lib" REQUIRED NO_DEFAULT_PATH NO_CMAKE_FIND_ROOT_PATH)
find_path(PPOCR_INCLUDE_DIR ppocrv6_engine.h PATHS "${PPOCR_SERVICE_ROOT}/native/include" REQUIRED NO_CMAKE_FIND_ROOT_PATH)
find_library(PPOCR_CORE_LIBRARY NAMES ppocrv6_rknn_core
  PATHS "${PPOCR_SERVICE_ROOT}/dist/rk3588/lib" "${PPOCR_SERVICE_ROOT}/dist/rk3588/bin" "${PPOCR_SERVICE_ROOT}/build-rk3588"
  REQUIRED NO_DEFAULT_PATH NO_CMAKE_FIND_ROOT_PATH)
find_path(DOCLAYOUT_INCLUDE_DIR doclayout_yolo_engine.h PATHS "${DOCLAYOUT_SERVICE_ROOT}/native/include" REQUIRED NO_CMAKE_FIND_ROOT_PATH)
find_library(DOCLAYOUT_CORE_LIBRARY NAMES doclayout_yolo_rknn_core
  PATHS "${DOCLAYOUT_SERVICE_ROOT}/dist/rk3588/lib" "${DOCLAYOUT_SERVICE_ROOT}/dist/rk3588/bin" "${DOCLAYOUT_SERVICE_ROOT}/build-rk3588"
  REQUIRED NO_DEFAULT_PATH NO_CMAKE_FIND_ROOT_PATH)
find_package(OpenCV REQUIRED COMPONENTS core imgcodecs imgproc)

add_library(document_vision_pdfium SHARED src/pdfium_document.cc)
target_include_directories(document_vision_pdfium PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include PRIVATE ${PDFIUM_INCLUDE_DIR})
target_link_libraries(document_vision_pdfium PRIVATE ${OpenCV_LIBS} PUBLIC ${PDFIUM_LIBRARY})
target_compile_options(document_vision_pdfium PRIVATE -Wall -Wextra -Wpedantic)
set_target_properties(document_vision_pdfium PROPERTIES BUILD_RPATH "$ORIGIN/../lib" INSTALL_RPATH "$ORIGIN/../lib")

add_library(document_vision_pipeline SHARED src/page_pipeline.cc)
target_include_directories(document_vision_pipeline
  PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include
  PRIVATE ${PDFIUM_INCLUDE_DIR} ${PPOCR_INCLUDE_DIR} ${DOCLAYOUT_INCLUDE_DIR})
target_link_libraries(document_vision_pipeline PRIVATE document_vision_pdfium ${PPOCR_CORE_LIBRARY} ${DOCLAYOUT_CORE_LIBRARY} ${OpenCV_LIBS})
target_compile_options(document_vision_pipeline PRIVATE -Wall -Wextra -Wpedantic)
set_target_properties(document_vision_pipeline PROPERTIES BUILD_RPATH "$ORIGIN" INSTALL_RPATH "$ORIGIN")

add_executable(pdfium_page apps/pdfium_page.cc)
target_link_libraries(pdfium_page PRIVATE document_vision_pdfium ${OpenCV_LIBS})
set_target_properties(pdfium_page PROPERTIES BUILD_RPATH "$ORIGIN:$ORIGIN/../lib" INSTALL_RPATH "$ORIGIN:$ORIGIN/../lib")

add_executable(pdf_page_parse apps/pdf_page_parse.cc)
target_link_libraries(pdf_page_parse PRIVATE document_vision_pipeline)
# The two prebuilt engine cores were built against the SDK's static OpenCV
# archive, whose optional image-codec symbols are resolved by the board's
# system OpenCV/WebP libraries at load time.  Do not force the final app link
# to re-resolve those implementation-private symbols.
target_link_options(pdf_page_parse PRIVATE "-Wl,--allow-shlib-undefined")
set_target_properties(pdf_page_parse PROPERTIES BUILD_RPATH "$ORIGIN:$ORIGIN/../lib" INSTALL_RPATH "$ORIGIN:$ORIGIN/../lib")

add_executable(document_vision_daemon apps/document_vision_daemon.cc)
target_link_libraries(document_vision_daemon PRIVATE document_vision_pipeline)
target_link_options(document_vision_daemon PRIVATE "-Wl,--allow-shlib-undefined")
set_target_properties(document_vision_daemon PROPERTIES BUILD_RPATH "$ORIGIN:$ORIGIN/../lib" INSTALL_RPATH "$ORIGIN:$ORIGIN/../lib")

install(TARGETS document_vision_pdfium document_vision_pipeline pdfium_page pdf_page_parse document_vision_daemon LIBRARY DESTINATION lib RUNTIME DESTINATION bin)
# Prebuilt distributions commonly expose libpdfium.so as a symlink. Resolve it
# at configure time so the staged/ADB package contains the actual ELF.
get_filename_component(PDFIUM_LIBRARY_REAL "${PDFIUM_LIBRARY}" REALPATH)
install(FILES "${PDFIUM_LIBRARY_REAL}" DESTINATION lib RENAME libpdfium.so)
get_filename_component(PPOCR_CORE_LIBRARY_REAL "${PPOCR_CORE_LIBRARY}" REALPATH)
get_filename_component(DOCLAYOUT_CORE_LIBRARY_REAL "${DOCLAYOUT_CORE_LIBRARY}" REALPATH)
install(FILES "${PPOCR_CORE_LIBRARY_REAL}" DESTINATION lib RENAME libppocrv6_rknn_core.so)
install(FILES "${DOCLAYOUT_CORE_LIBRARY_REAL}" DESTINATION lib RENAME libdoclayout_yolo_rknn_core.so)
