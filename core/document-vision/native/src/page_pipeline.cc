#include "page_pipeline.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <utility>
#include <vector>

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include "doclayout_yolo_engine.h"
#include "pdfium_document.h"
#include "ppocrv6_engine.h"

namespace document_vision {
namespace {

#ifndef MFD_CLOEXEC
#define MFD_CLOEXEC 0x0001U
#endif

[[noreturn]] void Fail(const std::string& message) { throw std::runtime_error(message); }

class MemoryImageFile {
 public:
  explicit MemoryImageFile(const cv::Mat& bgr) {
    if (bgr.empty()) Fail("cannot encode an empty image");
    std::vector<unsigned char> encoded;
    if (!cv::imencode(".png", bgr, encoded)) Fail("PNG memory encoding failed");
    fd_ = static_cast<int>(syscall(SYS_memfd_create, "document-vision-image", MFD_CLOEXEC));
    if (fd_ < 0) Fail("memfd_create failed");
    for (size_t offset = 0; offset < encoded.size();) {
      const ssize_t written = write(fd_, encoded.data() + offset, encoded.size() - offset);
      if (written <= 0) {
        close(fd_);
        fd_ = -1;
        Fail("writing image to memfd failed");
      }
      offset += static_cast<size_t>(written);
    }
    path_ = "/proc/self/fd/" + std::to_string(fd_);
  }
  ~MemoryImageFile() { if (fd_ >= 0) close(fd_); }
  MemoryImageFile(const MemoryImageFile&) = delete;
  MemoryImageFile& operator=(const MemoryImageFile&) = delete;
  const std::string& path() const { return path_; }

 private:
  int fd_ = -1;
  std::string path_;
};

struct PixelCharacter {
  std::string utf8;
  float left = 0.0F;
  float right = 0.0F;
  float top = 0.0F;
  float bottom = 0.0F;
};

bool IsVisibleCharacter(const PixelCharacter& character) {
  return character.utf8 != " " && character.utf8 != "\n" && character.utf8 != "\r";
}

float OverlapArea(const PixelCharacter& character, const std::array<float, 4>& region) {
  const float width = std::max(0.0F, std::min(character.right, region[2]) - std::max(character.left, region[0]));
  const float height = std::max(0.0F, std::min(character.bottom, region[3]) - std::max(character.top, region[1]));
  return width * height;
}

std::vector<PixelCharacter> ToPixelCharacters(const NativeTextPage& text, double page_height_points, int dpi) {
  const float scale = static_cast<float>(dpi) / 72.0F;
  std::vector<PixelCharacter> result;
  result.reserve(text.characters.size());
  for (const auto& character : text.characters) {
    PixelCharacter pixel;
    pixel.utf8 = character.utf8;
    pixel.left = static_cast<float>(character.left) * scale;
    pixel.right = static_cast<float>(character.right) * scale;
    pixel.top = static_cast<float>(page_height_points - character.top) * scale;
    pixel.bottom = static_cast<float>(page_height_points - character.bottom) * scale;
    result.push_back(std::move(pixel));
  }
  return result;
}

std::vector<std::vector<PixelCharacter>> GroupVisualLines(std::vector<PixelCharacter> selected) {
  selected.erase(std::remove_if(selected.begin(), selected.end(),
      [](const PixelCharacter& character) { return !IsVisibleCharacter(character); }), selected.end());
  std::sort(selected.begin(), selected.end(), [](const auto& a, const auto& b) {
    const float ay = (a.top + a.bottom) * 0.5F;
    const float by = (b.top + b.bottom) * 0.5F;
    return ay == by ? a.left < b.left : ay < by;
  });

  std::vector<std::vector<PixelCharacter>> lines;
  for (const auto& character : selected) {
    const float center = (character.top + character.bottom) * 0.5F;
    const float height = std::max(1.0F, character.bottom - character.top);
    if (lines.empty()) {
      lines.push_back({character});
      continue;
    }
    const auto& previous = lines.back().front();
    const float previous_center = (previous.top + previous.bottom) * 0.5F;
    const float tolerance = std::max(height, previous.bottom - previous.top) * 0.65F;
    if (std::abs(center - previous_center) > tolerance) lines.push_back({character});
    else lines.back().push_back(character);
  }
  for (auto& line : lines) {
    std::sort(line.begin(), line.end(), [](const auto& a, const auto& b) { return a.left < b.left; });
  }
  return lines;
}

std::string ReflowCharacters(std::vector<PixelCharacter> selected) {
  const auto lines = GroupVisualLines(std::move(selected));
  if (lines.empty()) return "";

  std::string output;
  for (size_t line_index = 0; line_index < lines.size(); ++line_index) {
    const auto& line = lines[line_index];
    float previous_right = -std::numeric_limits<float>::infinity();
    float previous_height = 0.0F;
    for (const auto& character : line) {
      const float height = std::max(1.0F, character.bottom - character.top);
      if (!output.empty() && std::isfinite(previous_right) &&
          character.left - previous_right > std::max(height, previous_height) * 0.75F) {
        output += ' ';
      }
      output += character.utf8;
      previous_right = character.right;
      previous_height = height;
    }
    if (line_index + 1 != lines.size()) output += '\n';
  }
  return output;
}

std::vector<std::vector<size_t>> AssignCharactersToTextRegions(
    const std::vector<PixelCharacter>& characters, const std::vector<std::array<float, 4>>& boxes) {
  std::vector<std::vector<size_t>> assignments(boxes.size());
  for (size_t char_index = 0; char_index < characters.size(); ++char_index) {
    const auto& character = characters[char_index];
    if (!IsVisibleCharacter(character)) continue;
    int best_region = -1;
    float best_area = 0.0F;
    for (size_t region_index = 0; region_index < boxes.size(); ++region_index) {
      const float area = OverlapArea(character, boxes[region_index]);
      if (area > best_area) {
        best_area = area;
        best_region = static_cast<int>(region_index);
      }
    }
    if (best_region >= 0) assignments[static_cast<size_t>(best_region)].push_back(char_index);
  }
  return assignments;
}

std::vector<PageBlock> BuildUnassignedNativeBlocks(const std::vector<PixelCharacter>& characters,
                                                    const std::vector<bool>& assigned) {
  std::vector<PixelCharacter> unassigned;
  for (size_t i = 0; i < characters.size(); ++i) {
    if (!assigned[i] && IsVisibleCharacter(characters[i])) unassigned.push_back(characters[i]);
  }

  std::vector<PageBlock> blocks;
  for (const auto& line : GroupVisualLines(std::move(unassigned))) {
    PageBlock block;
    block.label = "unassigned_native_text";
    block.class_id = -1;
    block.text_source = TextSource::kPdfium;
    block.text = ReflowCharacters(line);
    block.box = {std::numeric_limits<float>::infinity(), std::numeric_limits<float>::infinity(),
                 -std::numeric_limits<float>::infinity(), -std::numeric_limits<float>::infinity()};
    for (const auto& character : line) {
      block.box[0] = std::min(block.box[0], character.left);
      block.box[1] = std::min(block.box[1], character.top);
      block.box[2] = std::max(block.box[2], character.right);
      block.box[3] = std::max(block.box[3], character.bottom);
    }
    if (!block.text.empty()) blocks.push_back(std::move(block));
  }
  return blocks;
}

std::array<float, 4> BoundingBox(const std::array<int, 8>& polygon) {
  std::array<float, 4> box = {static_cast<float>(polygon[0]), static_cast<float>(polygon[1]),
                              static_cast<float>(polygon[0]), static_cast<float>(polygon[1])};
  for (size_t i = 2; i < polygon.size(); i += 2) {
    box[0] = std::min(box[0], static_cast<float>(polygon[i]));
    box[1] = std::min(box[1], static_cast<float>(polygon[i + 1]));
    box[2] = std::max(box[2], static_cast<float>(polygon[i]));
    box[3] = std::max(box[3], static_cast<float>(polygon[i + 1]));
  }
  return box;
}

float BoxOverlapArea(const std::array<float, 4>& a, const std::array<float, 4>& b) {
  const float width = std::max(0.0F, std::min(a[2], b[2]) - std::max(a[0], b[0]));
  const float height = std::max(0.0F, std::min(a[3], b[3]) - std::max(a[1], b[1]));
  return width * height;
}

int BestLayoutRegion(const std::array<float, 4>& box, const std::vector<doclayout_yolo::LayoutRegion>& regions) {
  int best_index = -1;
  float best_area = 0.0F;
  for (size_t i = 0; i < regions.size(); ++i) {
    const float area = BoxOverlapArea(box, regions[i].box);
    if (area > best_area) {
      best_area = area;
      best_index = static_cast<int>(i);
    }
  }
  return best_index;
}

}  // namespace

const char* ToString(TextSource source) {
  switch (source) {
    case TextSource::kPdfium: return "pdfium";
    case TextSource::kOcr: return "ocr";
    default: return "none";
  }
}

class PagePipeline::Impl {
 public:
  explicit Impl(PipelineConfig config) : config_(std::move(config)) {}

  void Initialize() {
    if (initialized_) return;
    if (config_.layout_model_path.empty() || config_.ocr_model_dir.empty()) {
      Fail("layout_model_path and ocr_model_dir are required");
    }
    if (config_.min_native_characters < 1 || config_.native_fast_path_min_characters < 1) {
      Fail("native character thresholds must be positive");
    }
    doclayout_yolo::EngineConfig layout_config;
    layout_config.model_path = config_.layout_model_path;
    layout_ = std::make_unique<doclayout_yolo::LayoutEngine>(std::move(layout_config));
    layout_->Initialize();
    ppocrv6::EngineConfig ocr_config;
    ocr_config.model_dir = config_.ocr_model_dir;
    ocr_config.dictionary_path = config_.ocr_dictionary_path.empty()
        ? config_.ocr_model_dir + "/ppocrv6_dict.txt" : config_.ocr_dictionary_path;
    ocr_ = std::make_unique<ppocrv6::OcrEngine>(std::move(ocr_config));
    ocr_->Initialize();
    initialized_ = true;
  }

  ParsedPage ParsePage(PdfiumDocument& document, int one_based_page) {
    if (one_based_page <= 0 || one_based_page > document.PageCount()) Fail("PDF page is out of range");
    const int index = one_based_page - 1;
    const NativeTextPage native = document.ExtractText(index);
    const double page_height_points = document.PageHeightPoints(index);
    const double page_width_points = document.PageWidthPoints(index);
    const auto characters = ToPixelCharacters(native, page_height_points, config_.render_dpi);

    // Native PDFs should not pay the visual-model cost merely because they
    // contain screenshots.  The text layer already gives stable glyph boxes
    // and reading order. Sparse/scanned pages still use the visual route.
    if (native.non_whitespace_count >= config_.native_fast_path_min_characters) {
      ParsedPage result;
      result.page_number = one_based_page;
      result.parse_route = "pdfium_native";
      const float scale = static_cast<float>(config_.render_dpi) / 72.0F;
      result.width = static_cast<int>(std::ceil(page_width_points * scale));
      result.height = static_cast<int>(std::ceil(page_height_points * scale));
      result.dpi = config_.render_dpi;
      result.native_text = native.utf8;
      result.native_character_count = native.character_count;
      result.blocks = BuildUnassignedNativeBlocks(characters, std::vector<bool>(characters.size(), false));
      for (auto& block : result.blocks) block.label = "native_text";
      std::sort(result.blocks.begin(), result.blocks.end(), [](const auto& a, const auto& b) {
        const float ay = (a.box[1] + a.box[3]) * 0.5F;
        const float by = (b.box[1] + b.box[3]) * 0.5F;
        return ay == by ? a.box[0] < b.box[0] : ay < by;
      });
      for (size_t i = 0; i < result.blocks.size(); ++i) result.blocks[i].reading_order = static_cast<int>(i);
      return result;
    }

    const cv::Mat page = document.RenderBgr(index, config_.render_dpi);
    MemoryImageFile page_image(page);
    const auto regions = layout_->DetectFile(page_image.path());
    // OCR must see the complete page. Layout is semantic metadata only;
    // using a Layout box as an OCR gate loses text whenever layout misses or
    // mislabels a region (for example text inside a figure).
    const auto ocr_results = ocr_->RecognizeFile(page_image.path());

    ParsedPage result;
    result.page_number = one_based_page;
    result.parse_route = "vision_fusion";
    result.width = page.cols;
    result.height = page.rows;
    result.dpi = config_.render_dpi;
    result.native_text = native.utf8;
    result.native_character_count = native.character_count;
    result.layout_regions.reserve(regions.size());
    for (const auto& region : regions) {
      PageBlock layout_block;
      layout_block.label = region.label;
      layout_block.class_id = region.class_id;
      layout_block.layout_score = region.score;
      layout_block.box = region.box;
      result.layout_regions.push_back(std::move(layout_block));
    }

    std::vector<std::array<float, 4>> ocr_boxes;
    ocr_boxes.reserve(ocr_results.size());
    for (const auto& ocr_result : ocr_results) ocr_boxes.push_back(BoundingBox(ocr_result.box));
    const auto assignments = AssignCharactersToTextRegions(characters, ocr_boxes);
    std::vector<bool> assigned(characters.size(), false);
    result.blocks.reserve(ocr_results.size() + characters.size());
    for (size_t ocr_index = 0; ocr_index < ocr_results.size(); ++ocr_index) {
      const auto& ocr_result = ocr_results[ocr_index];
      PageBlock block;
      block.box = ocr_boxes[ocr_index];
      block.polygon = ocr_result.box;
      block.has_polygon = true;
      block.det_score = ocr_result.det_score;
      block.rec_score = ocr_result.rec_score;
      const int layout_index = BestLayoutRegion(block.box, regions);
      if (layout_index >= 0) {
        const auto& layout = regions[static_cast<size_t>(layout_index)];
        block.label = layout.label;
        block.class_id = layout.class_id;
        block.layout_score = layout.score;
      } else {
        block.label = "unclassified_text";
      }
      std::vector<PixelCharacter> selected;
      selected.reserve(assignments[ocr_index].size());
      for (const size_t char_index : assignments[ocr_index]) {
        selected.push_back(characters[char_index]);
        assigned[char_index] = true;
      }
      const std::string native_region_text = ReflowCharacters(selected);
      if (static_cast<int>(selected.size()) >= config_.min_native_characters && !native_region_text.empty()) {
        block.text = native_region_text;
        block.text_source = TextSource::kPdfium;
      } else {
        block.text = ocr_result.text;
        block.text_source = block.text.empty() ? TextSource::kNone : TextSource::kOcr;
      }
      result.blocks.push_back(std::move(block));
    }
    auto unassigned_blocks = BuildUnassignedNativeBlocks(characters, assigned);
    result.blocks.insert(result.blocks.end(), std::make_move_iterator(unassigned_blocks.begin()),
                         std::make_move_iterator(unassigned_blocks.end()));
    std::sort(result.blocks.begin(), result.blocks.end(), [](const auto& a, const auto& b) {
      const float ay = (a.box[1] + a.box[3]) * 0.5F;
      const float by = (b.box[1] + b.box[3]) * 0.5F;
      return ay == by ? a.box[0] < b.box[0] : ay < by;
    });
    for (size_t i = 0; i < result.blocks.size(); ++i) result.blocks[i].reading_order = static_cast<int>(i);
    return result;
  }

  ParsedPage Parse(const std::string& pdf_path, int one_based_page) {
    if (!initialized_) Initialize();
    PdfiumDocument document(pdf_path);
    return ParsePage(document, one_based_page);
  }

  std::vector<ParsedPage> ParseDocument(const std::string& pdf_path) {
    if (!initialized_) Initialize();
    PdfiumDocument document(pdf_path);
    std::vector<ParsedPage> pages;
    pages.reserve(static_cast<size_t>(document.PageCount()));
    for (int page = 1; page <= document.PageCount(); ++page) {
      pages.push_back(ParsePage(document, page));
    }
    return pages;
  }

 private:
  PipelineConfig config_;
  std::unique_ptr<doclayout_yolo::LayoutEngine> layout_;
  std::unique_ptr<ppocrv6::OcrEngine> ocr_;
  bool initialized_ = false;
};

PagePipeline::PagePipeline(PipelineConfig config) : impl_(std::make_unique<Impl>(std::move(config))) {}
PagePipeline::~PagePipeline() = default;
void PagePipeline::Initialize() { impl_->Initialize(); }
ParsedPage PagePipeline::ParsePdfPage(const std::string& path, int page) { return impl_->Parse(path, page); }
std::vector<ParsedPage> PagePipeline::ParsePdfDocument(const std::string& path) {
  return impl_->ParseDocument(path);
}

}  // namespace document_vision
