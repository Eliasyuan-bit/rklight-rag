#include "pdfium_document.h"

#include <algorithm>
#include <cmath>
#include <cwctype>
#include <stdexcept>
#include <string_view>
#include <utility>
#include <vector>

#include <fpdf_text.h>
#include <fpdfview.h>
#include <opencv2/imgproc.hpp>

namespace document_vision {
namespace {

[[noreturn]] void Fail(const std::string& message) { throw std::runtime_error(message); }

class PdfiumRuntime {
 public:
  PdfiumRuntime() { FPDF_InitLibrary(); }
  ~PdfiumRuntime() { FPDF_DestroyLibrary(); }
  PdfiumRuntime(const PdfiumRuntime&) = delete;
  PdfiumRuntime& operator=(const PdfiumRuntime&) = delete;
};

PdfiumRuntime& Runtime() {
  static PdfiumRuntime runtime;
  return runtime;
}

std::string Utf16ToUtf8(const unsigned short* input, size_t length) {
  std::string output;
  output.reserve(length * 2);
  for (size_t index = 0; index < length; ++index) {
    uint32_t codepoint = input[index];
    if (codepoint >= 0xd800U && codepoint <= 0xdbffU && index + 1 < length) {
      const uint32_t low = input[index + 1];
      if (low >= 0xdc00U && low <= 0xdfffU) {
        codepoint = 0x10000U + ((codepoint - 0xd800U) << 10U) + (low - 0xdc00U);
        ++index;
      }
    }
    if (codepoint <= 0x7fU) output.push_back(static_cast<char>(codepoint));
    else if (codepoint <= 0x7ffU) {
      output.push_back(static_cast<char>(0xc0U | (codepoint >> 6U)));
      output.push_back(static_cast<char>(0x80U | (codepoint & 0x3fU)));
    } else if (codepoint <= 0xffffU) {
      output.push_back(static_cast<char>(0xe0U | (codepoint >> 12U)));
      output.push_back(static_cast<char>(0x80U | ((codepoint >> 6U) & 0x3fU)));
      output.push_back(static_cast<char>(0x80U | (codepoint & 0x3fU)));
    } else {
      output.push_back(static_cast<char>(0xf0U | (codepoint >> 18U)));
      output.push_back(static_cast<char>(0x80U | ((codepoint >> 12U) & 0x3fU)));
      output.push_back(static_cast<char>(0x80U | ((codepoint >> 6U) & 0x3fU)));
      output.push_back(static_cast<char>(0x80U | (codepoint & 0x3fU)));
    }
  }
  return output;
}

std::string CodepointToUtf8(uint32_t codepoint) {
  const unsigned short utf16[] = {
      static_cast<unsigned short>(codepoint <= 0xffffU ? codepoint : 0xd800U + ((codepoint - 0x10000U) >> 10U)),
      static_cast<unsigned short>(codepoint <= 0xffffU ? 0 : 0xdc00U + ((codepoint - 0x10000U) & 0x3ffU)),
  };
  return Utf16ToUtf8(utf16, codepoint <= 0xffffU ? 1U : 2U);
}

int CountNonWhitespace(const std::vector<unsigned short>& text, size_t length) {
  int count = 0;
  for (size_t i = 0; i < length; ++i) {
    if (!std::iswspace(static_cast<wint_t>(text[i])) && text[i] != 0) ++count;
  }
  return count;
}

class PageHandle {
 public:
  PageHandle(FPDF_DOCUMENT document, int page_index) : page_(FPDF_LoadPage(document, page_index)) {
    if (page_ == nullptr) Fail("FPDF_LoadPage failed for page " + std::to_string(page_index + 1));
  }
  ~PageHandle() { if (page_ != nullptr) FPDF_ClosePage(page_); }
  FPDF_PAGE get() const { return page_; }
 private:
  FPDF_PAGE page_ = nullptr;
};

}  // namespace

class PdfiumDocument::Impl {
 public:
  explicit Impl(const std::string& path) {
    static_cast<void>(Runtime());
    document_ = FPDF_LoadDocument(path.c_str(), nullptr);
    if (document_ == nullptr) Fail("FPDF_LoadDocument failed: " + path);
    pages_ = FPDF_GetPageCount(document_);
    if (pages_ < 0) Fail("FPDF_GetPageCount failed: " + path);
  }
  ~Impl() { if (document_ != nullptr) FPDF_CloseDocument(document_); }

  FPDF_DOCUMENT document() const { return document_; }
  int pages() const { return pages_; }

 private:
  FPDF_DOCUMENT document_ = nullptr;
  int pages_ = 0;
};

PdfiumDocument::PdfiumDocument(const std::string& path) : impl_(std::make_unique<Impl>(path)) {}
PdfiumDocument::~PdfiumDocument() = default;
int PdfiumDocument::PageCount() const { return impl_->pages(); }

double PdfiumDocument::PageWidthPoints(int page_index) const {
  if (page_index < 0 || page_index >= PageCount()) Fail("page index out of range");
  PageHandle page(impl_->document(), page_index);
  return FPDF_GetPageWidthF(page.get());
}

double PdfiumDocument::PageHeightPoints(int page_index) const {
  if (page_index < 0 || page_index >= PageCount()) Fail("page index out of range");
  PageHandle page(impl_->document(), page_index);
  return FPDF_GetPageHeightF(page.get());
}

NativeTextPage PdfiumDocument::ExtractText(int page_index) const {
  if (page_index < 0 || page_index >= PageCount()) Fail("page index out of range");
  PageHandle page(impl_->document(), page_index);
  FPDF_TEXTPAGE text_page = FPDFText_LoadPage(page.get());
  if (text_page == nullptr) Fail("FPDFText_LoadPage failed");
  const int characters = FPDFText_CountChars(text_page);
  if (characters < 0) {
    FPDFText_ClosePage(text_page);
    Fail("FPDFText_CountChars failed");
  }
  std::vector<unsigned short> utf16(static_cast<size_t>(characters) + 1U, 0);
  const int written = FPDFText_GetText(text_page, 0, characters, utf16.data());
  const size_t units = written > 0 ? static_cast<size_t>(written - 1) : 0U;  // trailing NUL is included.
  NativeTextPage result;
  result.utf8 = Utf16ToUtf8(utf16.data(), units);
  result.character_count = characters;
  result.non_whitespace_count = CountNonWhitespace(utf16, units);
  result.characters.reserve(static_cast<size_t>(characters));
  for (int i = 0; i < characters; ++i) {
    const uint32_t codepoint = FPDFText_GetUnicode(text_page, i);
    if (codepoint == 0) continue;
    NativeCharacter character;
    character.utf8 = CodepointToUtf8(codepoint);
    FPDFText_GetCharBox(text_page, i, &character.left, &character.right,
                        &character.bottom, &character.top);
    result.characters.push_back(std::move(character));
  }
  FPDFText_ClosePage(text_page);
  return result;
}

cv::Mat PdfiumDocument::RenderBgr(int page_index, int dpi) const {
  if (page_index < 0 || page_index >= PageCount()) Fail("page index out of range");
  if (dpi < 36 || dpi > 600) Fail("dpi must be in [36, 600]");
  PageHandle page(impl_->document(), page_index);
  const double page_width = FPDF_GetPageWidthF(page.get());
  const double page_height = FPDF_GetPageHeightF(page.get());
  const double scale = static_cast<double>(dpi) / 72.0;
  const int width = std::max(1, static_cast<int>(std::ceil(page_width * scale)));
  const int height = std::max(1, static_cast<int>(std::ceil(page_height * scale)));
  FPDF_BITMAP bitmap = FPDFBitmap_CreateEx(width, height, FPDFBitmap_BGRx, nullptr, 0);
  if (bitmap == nullptr) Fail("FPDFBitmap_CreateEx failed");
  FPDFBitmap_FillRect(bitmap, 0, 0, width, height, 0xffffffffU);
  FPDF_RenderPageBitmap(bitmap, page.get(), 0, 0, width, height, 0, FPDF_ANNOT);
  cv::Mat bgrx(height, width, CV_8UC4, FPDFBitmap_GetBuffer(bitmap), FPDFBitmap_GetStride(bitmap));
  cv::Mat bgr;
  cv::cvtColor(bgrx, bgr, cv::COLOR_BGRA2BGR);
  FPDFBitmap_Destroy(bitmap);
  return bgr;
}

}  // namespace document_vision
