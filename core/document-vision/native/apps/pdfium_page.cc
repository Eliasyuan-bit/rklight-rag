#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

#include <opencv2/imgcodecs.hpp>

#include "pdfium_document.h"

namespace {
void Usage(const char* program) {
  std::cerr << "Usage: " << program << " --input <file.pdf> --page <1-based>"
            << " [--text page.txt] [--render page.png] [--dpi 200]\n";
}
}  // namespace

int main(int argc, char** argv) {
  std::string input, text_path, render_path;
  int page = 0;
  int dpi = 200;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if ((arg == "--input" || arg == "--page" || arg == "--text" || arg == "--render" || arg == "--dpi") && i + 1 < argc) {
      const std::string value = argv[++i];
      if (arg == "--input") input = value;
      else if (arg == "--page") page = std::stoi(value);
      else if (arg == "--text") text_path = value;
      else if (arg == "--render") render_path = value;
      else dpi = std::stoi(value);
    } else { Usage(argv[0]); return 2; }
  }
  if (input.empty() || page <= 0 || (text_path.empty() && render_path.empty())) { Usage(argv[0]); return 2; }
  try {
    document_vision::PdfiumDocument document(input);
    if (page > document.PageCount()) throw std::runtime_error("page exceeds document page count");
    const int index = page - 1;
    if (!text_path.empty()) {
      const auto text = document.ExtractText(index);
      std::ofstream output(text_path, std::ios::binary);
      if (!output) throw std::runtime_error("cannot write text output: " + text_path);
      output << text.utf8;
      std::cout << "native_text_chars=" << text.character_count << " non_whitespace=" << text.non_whitespace_count
                << " usable=" << (text.HasUsableTextLayer() ? "true" : "false") << '\n';
    }
    if (!render_path.empty()) {
      const cv::Mat image = document.RenderBgr(index, dpi);
      if (!cv::imwrite(render_path, image)) throw std::runtime_error("cannot write image output: " + render_path);
      std::cout << "rendered=" << image.cols << "x" << image.rows << " dpi=" << dpi << '\n';
    }
  } catch (const std::exception& error) {
    std::cerr << "pdfium_page: " << error.what() << '\n';
    return 1;
  }
  return 0;
}
