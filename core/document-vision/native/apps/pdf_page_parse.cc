#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

#include "page_pipeline.h"

namespace {
std::string EscapeJson(const std::string& input) {
  std::string output;
  for (const unsigned char ch : input) {
    if (ch == '\\') output += "\\\\";
    else if (ch == '"') output += "\\\"";
    else if (ch == '\n') output += "\\n";
    else if (ch == '\r') output += "\\r";
    else if (ch == '\t') output += "\\t";
    else if (ch == '\b') output += "\\b";
    else if (ch == '\f') output += "\\f";
    else if (ch < 0x20U) {
      constexpr char kHex[] = "0123456789abcdef";
      output += "\\u00";
      output += kHex[(ch >> 4U) & 0x0fU];
      output += kHex[ch & 0x0fU];
    } else output += static_cast<char>(ch);
  }
  return output;
}
void WriteJson(std::ostream& out, const document_vision::ParsedPage& page) {
  out << "{\n  \"page\": " << page.page_number << ",\n  \"parse_route\": \"" << page.parse_route
      << "\",\n  \"width\": " << page.width
      << ",\n  \"height\": " << page.height << ",\n  \"dpi\": " << page.dpi
      << ",\n  \"native_character_count\": " << page.native_character_count
      << ",\n  \"native_text\": \"" << EscapeJson(page.native_text) << "\",\n  \"layout_regions\": [\n";
  for (size_t i = 0; i < page.layout_regions.size(); ++i) {
    const auto& b = page.layout_regions[i];
    out << "    {\"label\": \"" << EscapeJson(b.label) << "\", \"class_id\": " << b.class_id
        << ", \"layout_score\": " << b.layout_score << ", \"box\": [" << b.box[0] << ", "
        << b.box[1] << ", " << b.box[2] << ", " << b.box[3] << "]}"
        << (i + 1 == page.layout_regions.size() ? "\n" : ",\n");
  }
  out << "  ],\n  \"blocks\": [\n";
  for (size_t i = 0; i < page.blocks.size(); ++i) {
    const auto& b = page.blocks[i];
    out << "    {\"reading_order\": " << b.reading_order << ", \"label\": \"" << EscapeJson(b.label)
        << "\", \"class_id\": " << b.class_id << ", \"layout_score\": " << b.layout_score
        << ", \"text_source\": \"" << document_vision::ToString(b.text_source) << "\", \"text\": \""
        << EscapeJson(b.text) << "\", \"box\": [" << b.box[0] << ", " << b.box[1] << ", "
        << b.box[2] << ", " << b.box[3] << "]";
    if (b.has_polygon) {
      out << ", \"polygon\": [";
      for (size_t point = 0; point < b.polygon.size(); ++point) {
        out << b.polygon[point] << (point + 1 == b.polygon.size() ? "]" : ", ");
      }
      out << ", \"det_score\": " << b.det_score << ", \"rec_score\": " << b.rec_score;
    }
    out << "}" << (i + 1 == page.blocks.size() ? "\n" : ",\n");
  }
  out << "  ]\n}\n";
}
void Usage(const char* p) {
  std::cerr << "Usage: " << p << " --input file.pdf --page 1 --layout-model layout.rknn --ocr-models dir"
            << " [--dict dict.txt] [--dpi 200] [--min-native-characters 4] [--output page.json]\n";
}
}  // namespace

int main(int argc, char** argv) {
  document_vision::PipelineConfig config;
  std::string input, output;
  int page = 0;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if ((arg == "--input" || arg == "--page" || arg == "--layout-model" || arg == "--ocr-models" ||
         arg == "--dict" || arg == "--dpi" || arg == "--min-native-characters" || arg == "--output") && i + 1 < argc) {
      const std::string value = argv[++i];
      if (arg == "--input") input = value;
      else if (arg == "--page") page = std::stoi(value);
      else if (arg == "--layout-model") config.layout_model_path = value;
      else if (arg == "--ocr-models") config.ocr_model_dir = value;
      else if (arg == "--dict") config.ocr_dictionary_path = value;
      else if (arg == "--dpi") config.render_dpi = std::stoi(value);
      else if (arg == "--min-native-characters") config.min_native_characters = std::stoi(value);
      else output = value;
    } else { Usage(argv[0]); return 2; }
  }
  if (input.empty() || page <= 0 || config.layout_model_path.empty() || config.ocr_model_dir.empty()) { Usage(argv[0]); return 2; }
  try {
    document_vision::PagePipeline pipeline(config);
    pipeline.Initialize();
    const auto parsed = pipeline.ParsePdfPage(input, page);
    if (output.empty()) WriteJson(std::cout, parsed);
    else { std::ofstream file(output); if (!file) throw std::runtime_error("cannot write output: " + output); WriteJson(file, parsed); }
  } catch (const std::exception& error) { std::cerr << "pdf_page_parse: " << error.what() << '\n'; return 1; }
  return 0;
}
