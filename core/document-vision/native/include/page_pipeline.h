#pragma once

#include <array>
#include <memory>
#include <string>
#include <vector>

namespace document_vision {

enum class TextSource { kPdfium, kOcr, kNone };

struct PageBlock {
  std::string label;
  int class_id = -1;
  float layout_score = 0.0F;
  std::array<float, 4> box{};  // Original rendered-page pixels: x0,y0,x1,y1.
  // Preserved from PPOCRv6 for OCR-originated blocks. `box` remains the
  // axis-aligned convenience envelope used by layout matching.
  std::array<int, 8> polygon{};
  bool has_polygon = false;
  float det_score = -1.0F;
  float rec_score = -1.0F;
  std::string text;
  TextSource text_source = TextSource::kNone;
  int reading_order = -1;
};

struct ParsedPage {
  int page_number = 0;  // One-based.
  // `pdfium_native` bypasses visual models because the PDF text layer is
  // sufficiently dense; `vision_fusion` rendered and ran Layout + OCR.
  std::string parse_route;
  int width = 0;
  int height = 0;
  int dpi = 200;
  // Complete direct extraction in PDF object order. This is lossless at the
  // page level and is emitted even when layout detection misses a region.
  std::string native_text;
  int native_character_count = 0;
  // Geometry-only semantic regions from DocLayout-YOLO. Text blocks below are
  // produced independently, so a missed region cannot suppress page OCR.
  std::vector<PageBlock> layout_regions;
  std::vector<PageBlock> blocks;
};

struct PipelineConfig {
  std::string layout_model_path;
  std::string ocr_model_dir;
  std::string ocr_dictionary_path;
  int render_dpi = 200;
  int min_native_characters = 4;
  int native_fast_path_min_characters = 80;
};

class PagePipeline {
 public:
  explicit PagePipeline(PipelineConfig config);
  ~PagePipeline();
  PagePipeline(const PagePipeline&) = delete;
  PagePipeline& operator=(const PagePipeline&) = delete;

  // Initializes Layout and OCR once. ParsePdfPage is then safe to call
  // sequentially for each page of a document.
  void Initialize();
  ParsedPage ParsePdfPage(const std::string& pdf_path, int one_based_page);
  // Opens a PDF once and parses all of its pages with the already initialized
  // Layout/OCR contexts. This is the normal document-service entry point.
  std::vector<ParsedPage> ParsePdfDocument(const std::string& pdf_path);

 private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

const char* ToString(TextSource source);

}  // namespace document_vision
