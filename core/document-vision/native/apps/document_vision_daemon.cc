#include <chrono>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "page_pipeline.h"

namespace {
namespace fs = std::filesystem;

std::string EscapeJson(const std::string& value) {
  std::string out;
  out.reserve(value.size() + 8);
  for (const unsigned char ch : value) {
    switch (ch) {
      case '\\': out += "\\\\"; break;
      case '"': out += "\\\""; break;
      case '\n': out += "\\n"; break;
      case '\r': out += "\\r"; break;
      case '\t': out += "\\t"; break;
      case '\b': out += "\\b"; break;
      case '\f': out += "\\f"; break;
      default:
        // JSON permits neither raw NUL nor any other U+0000--U+001F
        // control character inside a string. PDF text layers can contain
        // vertical-tab and other non-printing glyphs, so escaping just CR/LF
        // and TAB is insufficient.
        if (ch < 0x20U) {
          constexpr char kHex[] = "0123456789abcdef";
          out += "\\u00";
          out += kHex[(ch >> 4U) & 0x0fU];
          out += kHex[ch & 0x0fU];
        } else {
          out += static_cast<char>(ch);
        }
        break;
    }
  }
  return out;
}

std::string JsonStringField(const std::string& line, const std::string& name) {
  const std::string key = "\"" + name + "\"";
  size_t pos = line.find(key);
  if (pos == std::string::npos) return "";
  pos = line.find(':', pos + key.size());
  if (pos == std::string::npos) throw std::runtime_error("invalid JSON field: " + name);
  pos = line.find('"', pos + 1);
  if (pos == std::string::npos) throw std::runtime_error("field is not a JSON string: " + name);
  std::string value;
  bool escaped = false;
  for (++pos; pos < line.size(); ++pos) {
    const char ch = line[pos];
    if (escaped) {
      if (ch == 'n') value += '\n';
      else if (ch == 'r') value += '\r';
      else if (ch == 't') value += '\t';
      else value += ch;
      escaped = false;
    } else if (ch == '\\') {
      escaped = true;
    } else if (ch == '"') {
      return value;
    } else {
      value += ch;
    }
  }
  throw std::runtime_error("unterminated JSON string: " + name);
}

void WritePageJson(std::ostream& out, const document_vision::ParsedPage& page, const std::string& indent = "") {
  const std::string i1 = indent + "  ";
  const std::string i2 = indent + "    ";
  out << indent << "{\n" << i1 << "\"page\": " << page.page_number << ",\n"
      << i1 << "\"parse_route\": \"" << page.parse_route << "\",\n"
      << i1 << "\"width\": " << page.width << ",\n" << i1 << "\"height\": " << page.height << ",\n"
      << i1 << "\"dpi\": " << page.dpi << ",\n" << i1 << "\"native_character_count\": "
      << page.native_character_count << ",\n" << i1 << "\"native_text\": \"" << EscapeJson(page.native_text)
      << "\",\n" << i1 << "\"layout_regions\": [\n";
  for (size_t n = 0; n < page.layout_regions.size(); ++n) {
    const auto& b = page.layout_regions[n];
    out << i2 << "{\"label\": \"" << EscapeJson(b.label) << "\", \"class_id\": " << b.class_id
        << ", \"layout_score\": " << b.layout_score << ", \"box\": [" << b.box[0] << ", " << b.box[1]
        << ", " << b.box[2] << ", " << b.box[3] << "]}" << (n + 1 == page.layout_regions.size() ? "\n" : ",\n");
  }
  out << i1 << "],\n" << i1 << "\"blocks\": [\n";
  for (size_t n = 0; n < page.blocks.size(); ++n) {
    const auto& b = page.blocks[n];
    out << i2 << "{\"reading_order\": " << b.reading_order << ", \"label\": \"" << EscapeJson(b.label)
        << "\", \"class_id\": " << b.class_id << ", \"layout_score\": " << b.layout_score
        << ", \"text_source\": \"" << document_vision::ToString(b.text_source) << "\", \"text\": \""
        << EscapeJson(b.text) << "\", \"box\": [" << b.box[0] << ", " << b.box[1] << ", " << b.box[2]
        << ", " << b.box[3] << "]";
    if (b.has_polygon) {
      out << ", \"polygon\": [";
      for (size_t point = 0; point < b.polygon.size(); ++point) out << b.polygon[point] << (point + 1 == b.polygon.size() ? "]" : ", ");
      out << ", \"det_score\": " << b.det_score << ", \"rec_score\": " << b.rec_score;
    }
    out << "}" << (n + 1 == page.blocks.size() ? "\n" : ",\n");
  }
  out << i1 << "]\n" << indent << "}";
}

bool IncludeInMarkdown(const document_vision::PageBlock& block) {
  // A figure normally has no PDF text layer. Full-page OCR is still needed for
  // scanned documents, but OCR inside a layout-detected figure is usually UI
  // chrome, labels, or rasterized text that does not belong in the document's
  // reading stream. Keep the geometry in JSON, but exclude only this narrow
  // OCR fallback case. Native PDF text and tables remain intact.
  return !(block.label == "figure" && block.text_source == document_vision::TextSource::kOcr);
}

void WriteMarkdown(std::ostream& out, const std::vector<document_vision::ParsedPage>& pages) {
  for (const auto& page : pages) {
    out << "# Page " << page.page_number << "\n\n";
    for (const auto& block : page.blocks) {
      if (IncludeInMarkdown(block) && !block.text.empty()) out << block.text << "\n\n";
    }
  }
}

void WriteOutputs(const std::string& source, const fs::path& output_dir,
                  const std::vector<document_vision::ParsedPage>& pages) {
  fs::create_directories(output_dir / "pages");
  for (const auto& page : pages) {
    char name[32];
    std::snprintf(name, sizeof(name), "page-%03d.json", page.page_number);
    std::ofstream file(output_dir / "pages" / name);
    if (!file) throw std::runtime_error("cannot write page result");
    WritePageJson(file, page);
    file << '\n';
  }
  std::ofstream document(output_dir / "document.json");
  if (!document) throw std::runtime_error("cannot write document.json");
  document << "{\n  \"source\": \"" << EscapeJson(source) << "\",\n  \"page_count\": " << pages.size()
           << ",\n  \"pages\": [\n";
  for (size_t n = 0; n < pages.size(); ++n) {
    WritePageJson(document, pages[n], "    ");
    document << (n + 1 == pages.size() ? "\n" : ",\n");
  }
  document << "  ]\n}\n";
  std::ofstream markdown(output_dir / "document.md");
  if (!markdown) throw std::runtime_error("cannot write document.md");
  WriteMarkdown(markdown, pages);
}

void WriteError(const std::string& id, const std::string& error) {
  std::cout << "{\"id\":\"" << EscapeJson(id) << "\",\"ok\":false,\"error\":\"" << EscapeJson(error) << "\"}" << std::endl;
}

void Usage(const char* program) {
  std::cerr << "Usage: " << program << " --layout-model <model.rknn> --ocr-models <dir> [--dict <dict.txt>] [--dpi 200]\n"
            << "Reads JSON Lines: {\"id\":\"job-1\",\"input\":\"/path/document.pdf\",\"output_dir\":\"/path/job\"}\n";
}
}  // namespace

int main(int argc, char** argv) {
  document_vision::PipelineConfig config;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if ((arg == "--layout-model" || arg == "--ocr-models" || arg == "--dict" || arg == "--dpi") && i + 1 < argc) {
      const std::string value = argv[++i];
      if (arg == "--layout-model") config.layout_model_path = value;
      else if (arg == "--ocr-models") config.ocr_model_dir = value;
      else if (arg == "--dict") config.ocr_dictionary_path = value;
      else config.render_dpi = std::stoi(value);
    } else { Usage(argv[0]); return 2; }
  }
  if (config.layout_model_path.empty() || config.ocr_model_dir.empty()) { Usage(argv[0]); return 2; }
  try {
    document_vision::PagePipeline pipeline(config);
    pipeline.Initialize();  // Intentionally outside request timing: initialized once per daemon lifetime.
    std::cout << "{\"ready\":true}" << std::endl;
    std::string request;
    while (std::getline(std::cin, request)) {
      if (request.empty()) continue;
      std::string id;
      try {
        id = JsonStringField(request, "id");
        const std::string input = JsonStringField(request, "input");
        const std::string output_dir = JsonStringField(request, "output_dir");
        if (input.empty() || output_dir.empty()) throw std::runtime_error("input and output_dir are required string fields");
        const auto started = std::chrono::steady_clock::now();
        const auto pages = pipeline.ParsePdfDocument(input);
        WriteOutputs(input, output_dir, pages);
        const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started).count();
        std::cout << "{\"id\":\"" << EscapeJson(id) << "\",\"ok\":true,\"page_count\":" << pages.size()
                  << ",\"output_dir\":\"" << EscapeJson(output_dir) << "\",\"elapsed_ms\":" << elapsed << "}" << std::endl;
      } catch (const std::exception& error) { WriteError(id, error.what()); }
    }
  } catch (const std::exception& error) {
    std::cerr << "document_vision_daemon: initialization failed: " << error.what() << '\n';
    return 1;
  }
  return 0;
}
