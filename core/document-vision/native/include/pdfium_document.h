#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include <opencv2/core/mat.hpp>

namespace document_vision {

struct NativeCharacter {
  std::string utf8;
  // PDF user-space coordinates: origin at the bottom-left of the page.
  double left = 0.0;
  double right = 0.0;
  double bottom = 0.0;
  double top = 0.0;
};

struct NativeTextPage {
  std::string utf8;
  int character_count = 0;
  int non_whitespace_count = 0;
  std::vector<NativeCharacter> characters;

  // A conservative routing signal. It says that a usable native text layer
  // exists; it does not claim that PDF content order is semantic reading order.
  bool HasUsableTextLayer() const { return non_whitespace_count >= 24; }
};

class PdfiumDocument {
 public:
  explicit PdfiumDocument(const std::string& path);
  ~PdfiumDocument();
  PdfiumDocument(const PdfiumDocument&) = delete;
  PdfiumDocument& operator=(const PdfiumDocument&) = delete;

  int PageCount() const;
  // Page dimensions in PDF points (1 / 72 inch).  These are used to map
  // PDF text glyph boxes exactly onto the rendered page pixels.
  double PageWidthPoints(int page_index) const;
  double PageHeightPoints(int page_index) const;
  NativeTextPage ExtractText(int page_index) const;
  // Render a page to BGR8. PDF points are scaled at dpi / 72.
  cv::Mat RenderBgr(int page_index, int dpi = 200) const;

 private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace document_vision
