#include <onnxruntime_cxx_api.h>
#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"
#define STB_IMAGE_RESIZE_IMPLEMENTATION
#include "stb_image_resize.h"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

using json = nlohmann::json;
using Clock = std::chrono::steady_clock;

static double ms(Clock::time_point a, Clock::time_point b) {
    return std::chrono::duration<double, std::milli>(b - a).count();
}

static const std::unordered_map<int, std::string> TOK = {
    {0, "<pad>"}, {1, "<unk>"}, {2, "<start>"}, {3, "<end>"},
    {4, "ecel"},  {5, "fcel"},  {6, "lcel"},    {7, "ucel"},
    {8, "xcel"},  {9, "nl"},    {10, "ched"},   {11, "rhed"},
    {12, "srow"},
};

struct Cell {
    int id = 0;
    int row = 0;
    int col = 0;
    int row_span = 1;
    int col_span = 1;
    int cls = 2;
    std::string label = "body";
    std::array<float, 4> box = {0, 0, 0, 0};  // normalized x1,y1,x2,y2
    std::string text;
};

struct OcrText {
    std::string text;
    float cx = 0;
    float cy = 0;
};

static std::vector<std::string> names(Ort::Session& s, bool input) {
    Ort::AllocatorWithDefaultOptions a;
    std::vector<std::string> r;
    size_t n = input ? s.GetInputCount() : s.GetOutputCount();
    for (size_t i = 0; i < n; ++i) {
        auto p = input ? s.GetInputNameAllocated(i, a)
                       : s.GetOutputNameAllocated(i, a);
        r.emplace_back(p.get());
    }
    return r;
}

static Ort::Value tensor_f32(std::vector<float>& x,
                             const std::vector<int64_t>& shape) {
    return Ort::Value::CreateTensor<float>(
        Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault),
        x.data(), x.size(), shape.data(), shape.size());
}

static Ort::Value tensor_i64(std::vector<int64_t>& x,
                             const std::vector<int64_t>& shape) {
    return Ort::Value::CreateTensor<int64_t>(
        Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault),
        x.data(), x.size(), shape.data(), shape.size());
}

static Ort::Value alias_f32(Ort::Value& v) {
    auto info = v.GetTensorTypeAndShapeInfo();
    auto shape = info.GetShape();
    return Ort::Value::CreateTensor<float>(
        Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault),
        v.GetTensorMutableData<float>(), info.GetElementCount(), shape.data(),
        shape.size());
}

static std::string json_escape(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 8);
    for (char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default: out += c;
        }
    }
    return out;
}

static std::string shell_quote(const std::string& s) {
    std::string out = "'";
    for (char c : s) {
        if (c == '\'') out += "'\\''";
        else out += c;
    }
    return out + "'";
}

static json run_ocr(const std::string& image_path, const std::string& daemon,
                    const std::string& models, const std::string& libdir,
                    const std::string& out_file) {
    std::string cmd = "LD_LIBRARY_PATH=" + shell_quote(libdir) + " " +
                      shell_quote(daemon) + " --models " + shell_quote(models) +
                      " > " + shell_quote(out_file) + " 2>/dev/null";
    FILE* p = popen(cmd.c_str(), "w");
    if (!p) return json();
    std::string req = "{\"id\":\"tableformer\",\"input\":\"" +
                      json_escape(image_path) + "\"}\n";
    fwrite(req.data(), 1, req.size(), p);
    int rc = pclose(p);
    (void)rc;
    std::ifstream f(out_file);
    std::string content((std::istreambuf_iterator<char>(f)),
                        std::istreambuf_iterator<char>());
    f.close();
    std::remove(out_file.c_str());
    if (content.empty()) return json();
    try {
        return json::parse(content);
    } catch (...) {
        return json();
    }
}

static bool good_down(int t) {
    return t == 5 || t == 10 || t == 11 || t == 12 || t == 4 || t == 6 || t == 9;
}

static bool good_right(int t) {
    return t == 5 || t == 10 || t == 11 || t == 12 || t == 4 || t == 7 || t == 9;
}

static int check_down(const std::vector<std::vector<int>>& rows, int x, int y) {
    int distance = 1;
    int elem = 7;  // ucel
    while (!good_down(elem) && y < static_cast<int>(rows.size()) - 1) {
        y += 1;
        distance += 1;
        elem = rows[y][x];
    }
    if (good_down(elem)) distance -= 1;
    return distance;
}

static int check_right(const std::vector<std::vector<int>>& rows, int x, int y) {
    int distance = 1;
    int elem = 6;  // lcel
    while (!good_right(elem) &&
           x < static_cast<int>(rows[y].size()) - 1) {
        x += 1;
        distance += 1;
        elem = rows[y][x];
    }
    if (good_right(elem)) distance -= 1;
    return distance;
}

static std::array<float, 4> merge_bbox(const std::array<float, 4>& b1,
                                       const std::array<float, 4>& b2) {
    // b1, b2 are cxcywh.
    float new_w = (b2[0] + b2[2] / 2.0f) - (b1[0] - b1[2] / 2.0f);
    float new_h = (b2[1] + b2[3] / 2.0f) - (b1[1] - b1[3] / 2.0f);
    float new_left = b1[0] - b1[2] / 2.0f;
    float new_top =
        std::min(b2[1] - b2[3] / 2.0f, b1[1] - b1[3] / 2.0f);
    float new_cx = new_left + new_w / 2.0f;
    float new_cy = new_top + new_h / 2.0f;
    return {new_cx, new_cy, new_w, new_h};
}

static std::array<float, 4> cxcywh_to_xyxy(const std::array<float, 4>& b) {
    return {b[0] - b[2] / 2.0f, b[1] - b[3] / 2.0f, b[0] + b[2] / 2.0f,
            b[1] + b[3] / 2.0f};
}

static std::vector<Cell> build_cells(
    const std::vector<int>& structure,
    const std::vector<std::array<float, 4>>& boxes,
    const std::vector<int>& classes) {
    std::vector<std::vector<int>> rows;
    std::vector<int> cur;
    for (int t : structure) {
        if (t == 9) {
            rows.push_back(cur);
            cur.clear();
        } else {
            cur.push_back(t);
        }
    }
    if (!cur.empty()) rows.push_back(cur);
    if (rows.empty()) return {};

    size_t max_len = 0;
    for (auto& r : rows) max_len = std::max(max_len, r.size());
    for (auto& r : rows) {
        while (r.size() < max_len) r.push_back(6);  // pad with lcel
    }

    std::vector<Cell> cells;
    int cell_id = 0;
    for (size_t y = 0; y < rows.size(); ++y) {
        for (size_t x = 0; x < rows[y].size(); ++x) {
            int t = rows[y][x];
            if (t != 5 && t != 4 && t != 10 && t != 11 && t != 12) continue;

            int rdist = 0, ddist = 0, xrdist = 0, xddist = 0;
            bool span = false;
            if (x + 1 < rows[y].size() && rows[y][x + 1] == 6) {
                rdist = check_right(rows, static_cast<int>(x),
                                    static_cast<int>(y));
                span = true;
            }
            if (y + 1 < rows.size() && rows[y + 1][x] == 7) {
                ddist = check_down(rows, static_cast<int>(x),
                                   static_cast<int>(y));
                span = true;
            }
            if (x + 1 < rows[y].size() && rows[y][x + 1] == 8) {
                xrdist = check_right(rows, static_cast<int>(x),
                                     static_cast<int>(y));
                xddist = check_down(rows, static_cast<int>(x),
                                    static_cast<int>(y));
                span = true;
            }
            (void)span;

            Cell c;
            c.id = cell_id;
            c.row = static_cast<int>(y);
            c.col = static_cast<int>(x);
            c.label = TOK.at(t);
            c.col_span = rdist > 1 ? rdist : (xrdist > 1 ? xrdist : 1);
            c.row_span = ddist > 1 ? ddist : (xddist > 1 ? xddist : 1);
            if (cell_id < static_cast<int>(boxes.size())) c.box = boxes[cell_id];
            if (cell_id < static_cast<int>(classes.size())) c.cls = classes[cell_id];
            cells.push_back(c);
            cell_id += 1;
        }
    }
    return cells;
}

static void write_outputs(const std::string& md_path,
                          const std::string& json_path,
                          const std::vector<Cell>& cells, int nrows, int ncols) {
    std::vector<std::vector<std::string>> grid(
        static_cast<size_t>(nrows),
        std::vector<std::string>(static_cast<size_t>(ncols)));
    for (const auto& c : cells) {
        if (c.row >= 0 && c.row < nrows && c.col >= 0 && c.col < ncols) {
            grid[c.row][c.col] = c.text;
        }
    }

    bool header = false;
    for (const auto& c : cells) {
        if (c.row == 0 && c.label == "ched") header = true;
    }

    std::ofstream f(md_path);
    if (!f) throw std::runtime_error("cannot open output");
    for (int r = 0; r < nrows; ++r) {
        f << "|";
        for (int col = 0; col < ncols; ++col) {
            std::string cell = grid[r][col];
            for (char& ch : cell)
                if (ch == '|') ch = ' ';
            f << " " << cell << " |";
        }
        f << "\n";
        if (r == 0 && header) {
            f << "|";
            for (int col = 0; col < ncols; ++col) f << " --- |";
            f << "\n";
        }
    }
    f.close();

    json j = json::array();
    for (const auto& c : cells) {
        j.push_back({{"id", c.id},
                     {"row", c.row},
                     {"col", c.col},
                     {"row_span", c.row_span},
                     {"col_span", c.col_span},
                     {"label", c.label},
                     {"class", c.cls},
                     {"bbox", {c.box[0], c.box[1], c.box[2], c.box[3]}},
                     {"text", c.text}});
    }
    std::ofstream jf(json_path);
    if (jf) jf << j.dump(2) << "\n";
}

int main(int argc, char** argv) {
    if (argc < 3 || argc > 7) {
        std::cerr
            << "usage: tableformer_cpu IMAGE OUTPUT.md [encoder.onnx] "
               "[decoder.onnx] [bbox.onnx] [max_steps]\n";
        return 2;
    }
    const std::string image_path = argv[1];
    const std::string md_path = argv[2];
    const std::string enc_path = argc >= 4 ? argv[3] : "encoder.onnx";
    const std::string dec_path = argc >= 5 ? argv[4] : "decoder.onnx";
    const std::string bbox_path = argc >= 6 ? argv[5] : "bbox.onnx";
    const size_t max_steps =
        argc >= 7 ? static_cast<size_t>(std::stoul(argv[6])) : 256;

    const std::string json_path = md_path + ".cells.json";
    const std::string ocr_daemon =
        getenv("TF_OCR_DAEMON")
            ? getenv("TF_OCR_DAEMON")
            : "/userdata/ppocrv6-rknn-service/bin/ppocrv6_ocr_daemon";
    const std::string ocr_models =
        getenv("TF_OCR_MODELS")
            ? getenv("TF_OCR_MODELS")
            : "/userdata/ppocrv6-rknn-service/models";
    const std::string ocr_lib =
        getenv("TF_OCR_LIB")
            ? getenv("TF_OCR_LIB")
            : "/userdata/ppocrv6-rknn-service/lib";
    const bool enable_ocr =
        !getenv("TF_OCR_DISABLE") ||
        std::string(getenv("TF_OCR_DISABLE")) != "1";

    try {
        Ort::Env env(ORT_LOGGING_LEVEL_WARNING, "tableformer_cpu");
        Ort::SessionOptions so;
        so.SetIntraOpNumThreads(8);
        so.SetInterOpNumThreads(1);
        so.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);

        int src_w = 0, src_h = 0, src_c = 0;
        unsigned char* src =
            stbi_load(image_path.c_str(), &src_w, &src_h, &src_c, 3);
        if (!src)
            throw std::runtime_error(std::string("cannot read image: ") +
                                     stbi_failure_reason());

        auto t0 = Clock::now();
        std::vector<unsigned char> im(448 * 448 * 3);
        if (!stbir_resize_uint8(src, src_w, src_h, 0, im.data(), 448, 448, 0, 3)) {
            stbi_image_free(src);
            throw std::runtime_error("image resize failed");
        }
        stbi_image_free(src);

        const float mean[3] = {0.94247851f, 0.94254675f, 0.94292611f};
        const float sd[3] = {0.17910956f, 0.17940403f, 0.17931663f};
        std::vector<float> pix(1 * 3 * 448 * 448);
        // The reference model feeds each channel transposed (H/W swapped).
        for (int y = 0; y < 448; ++y)
            for (int x = 0; x < 448; ++x)
                for (int c = 0; c < 3; ++c)
                    pix[c * 448 * 448 + x * 448 + y] =
                        (im[(y * 448 + x) * 3 + c] / 255.0f - mean[c]) / sd[c];
        auto t1 = Clock::now();

        Ort::Session enc(env, enc_path.c_str(), so);
        auto en = names(enc, true), eo = names(enc, false);
        std::vector<const char*> ein, eout;
        for (auto& s : en) ein.push_back(s.c_str());
        for (auto& s : eo) eout.push_back(s.c_str());
        std::vector<int64_t> ish = {1, 3, 448, 448};
        auto iv = tensor_f32(pix, ish);
        auto encout =
            enc.Run(Ort::RunOptions{nullptr}, ein.data(), &iv, 1, eout.data(),
                    eout.size());
        std::unordered_map<std::string, size_t> ei;
        for (size_t i = 0; i < eo.size(); ++i) ei[eo[i]] = i;
        auto t2 = Clock::now();

        Ort::Session dec(env, dec_path.c_str(), so);
        auto dn = names(dec, true), dno = names(dec, false);
        std::vector<const char*> din, dout;
        for (auto& s : dn) din.push_back(s.c_str());
        for (auto& s : dno) dout.push_back(s.c_str());

        std::vector<int> ids = {2};  // <start>
        std::vector<int> seq;
        std::vector<std::vector<float>> tag_H_buf;
        std::map<int, int> bboxes_to_merge;
        bool skip_next_tag = true, prev_tag_ucel = false, first_lcel = true;
        int cur_bbox_ind = -1, bbox_ind = 0;
        std::vector<float> cache;
        std::vector<int64_t> cshape = {6, 0, 1, 512};
        size_t steps = 0;

        while (steps++ < max_steps) {
            std::vector<int64_t> tag(ids.begin(), ids.end());
            std::vector<int64_t> tshape = {static_cast<int64_t>(tag.size()), 1};
            std::vector<Ort::Value> args;
            args.reserve(4);
            args.push_back(tensor_i64(tag, tshape));
            args.push_back(alias_f32(encout[ei.at("cross_k")]));
            args.push_back(alias_f32(encout[ei.at("cross_v")]));
            args.push_back(tensor_f32(cache, cshape));
            auto out =
                dec.Run(Ort::RunOptions{nullptr}, din.data(), args.data(),
                        args.size(), dout.data(), dout.size());

            auto li = out[0].GetTensorData<float>();
            int best = 0;
            for (int i = 1; i < 13; ++i)
                if (li[i] > li[best]) best = i;

            auto hi = out[1].GetTensorData<float>();
            std::vector<float> cur_hidden(hi, hi + 512);

            int new_tag = best;
            if (new_tag == 8) new_tag = 6;                   // xcel -> lcel
            if (prev_tag_ucel && new_tag == 6) new_tag = 5;  // lcel -> fcel

            if (new_tag == 3) {
                ids.push_back(new_tag);
                break;
            }
            seq.push_back(new_tag);

            if (!skip_next_tag) {
                bool cell_like = new_tag == 5 || new_tag == 4 ||
                                 new_tag == 10 || new_tag == 11 ||
                                 new_tag == 12 || new_tag == 9 || new_tag == 7;
                if (cell_like) {
                    tag_H_buf.push_back(cur_hidden);
                    if (!first_lcel) bboxes_to_merge[cur_bbox_ind] = bbox_ind;
                    bbox_ind += 1;
                }
            }

            if (new_tag != 6) {
                first_lcel = true;
            } else if (first_lcel) {
                tag_H_buf.push_back(cur_hidden);
                first_lcel = false;
                cur_bbox_ind = bbox_ind;
                bboxes_to_merge[cur_bbox_ind] = -1;
                bbox_ind += 1;
            }

            skip_next_tag = (new_tag == 9 || new_tag == 7 || new_tag == 8);
            prev_tag_ucel = (new_tag == 7);

            auto cs = out[2].GetTensorTypeAndShapeInfo().GetShape();
            size_t n = out[2].GetTensorTypeAndShapeInfo().GetElementCount();
            cache.assign(out[2].GetTensorData<float>(),
                         out[2].GetTensorData<float>() + n);
            cshape = cs;
            ids.push_back(new_tag);
        }
        auto t3 = Clock::now();

        std::vector<std::array<float, 4>> boxes;
        std::vector<int> classes;
        const size_t ncells = tag_H_buf.size();
        if (ncells > 0) {
            std::vector<float> tag_h(ncells * 512);
            for (size_t i = 0; i < ncells; ++i)
                std::copy(tag_H_buf[i].begin(), tag_H_buf[i].end(),
                          tag_h.begin() + i * 512);

            Ort::Session bbox(env, bbox_path.c_str(), so);
            auto bin = names(bbox, true), bout = names(bbox, false);
            std::vector<const char*> bin_c, bout_c;
            for (auto& s : bin) bin_c.push_back(s.c_str());
            for (auto& s : bout) bout_c.push_back(s.c_str());
            std::vector<Ort::Value> bargs;
            bargs.push_back(alias_f32(encout[ei.at("enc_out")]));
            bargs.push_back(
                tensor_f32(tag_h, {static_cast<int64_t>(ncells), 512}));
            auto bres =
                bbox.Run(Ort::RunOptions{nullptr}, bin_c.data(), bargs.data(),
                         bargs.size(), bout_c.data(), bout_c.size());
            std::unordered_map<std::string, size_t> bi;
            for (size_t i = 0; i < bout.size(); ++i) bi[bout[i]] = i;

            auto* box_data = bres[bi.at("boxes")].GetTensorData<float>();
            auto* cls_data = bres[bi.at("classes")].GetTensorData<float>();
            std::vector<std::array<float, 4>> raw_boxes(ncells);
            std::vector<int> raw_classes(ncells);
            for (size_t i = 0; i < ncells; ++i) {
                raw_boxes[i] = {box_data[i * 4], box_data[i * 4 + 1],
                                box_data[i * 4 + 2], box_data[i * 4 + 3]};
                int c0 = static_cast<int>(cls_data[i * 3]);
                int c1 = static_cast<int>(cls_data[i * 3 + 1]);
                int c2 = static_cast<int>(cls_data[i * 3 + 2]);
                raw_classes[i] = (c0 >= c1 && c0 >= c2) ? 0 : (c1 >= c2 ? 1 : 2);
            }

            std::vector<char> skip_box(ncells, 0);
            for (size_t i = 0; i < ncells; ++i) {
                if (skip_box[i]) continue;
                auto it = bboxes_to_merge.find(static_cast<int>(i));
                if (it != bboxes_to_merge.end() && it->second >= 0 &&
                    it->second != static_cast<int>(i) &&
                    it->second < static_cast<int>(ncells)) {
                    boxes.push_back(cxcywh_to_xyxy(
                        merge_bbox(raw_boxes[i], raw_boxes[it->second])));
                    classes.push_back(raw_classes[i]);
                    skip_box[it->second] = 1;
                } else {
                    boxes.push_back(cxcywh_to_xyxy(raw_boxes[i]));
                    classes.push_back(raw_classes[i]);
                }
            }
        }
        auto t4 = Clock::now();

        auto cells = build_cells(seq, boxes, classes);

        int nrows = 0, ncols = 0;
        for (const auto& c : cells) {
            nrows = std::max(nrows, c.row + c.row_span);
            ncols = std::max(ncols, c.col + c.col_span);
        }
        if (cells.empty()) {
            nrows = static_cast<int>(std::count(seq.begin(), seq.end(), 9));
            int cur_cols = 0;
            for (int t : seq) {
                if (t == 9) {
                    ncols = std::max(ncols, cur_cols);
                    cur_cols = 0;
                } else {
                    cur_cols += 1;
                }
            }
            ncols = std::max(ncols, cur_cols);
        }

        auto t5 = Clock::now();
        if (enable_ocr && !cells.empty()) {
            json ocr = run_ocr(image_path, ocr_daemon, ocr_models, ocr_lib,
                               md_path + ".ocr.json");
            if (ocr.value("ok", false)) {
                std::vector<OcrText> texts;
                for (const auto& t : ocr["texts"]) {
                    if (!t.contains("text") || !t.contains("box")) continue;
                    OcrText o;
                    o.text = t["text"].get<std::string>();
                    auto b = t["box"];
                    float sum_x = 0, sum_y = 0;
                    int npts = 0;
                    for (const auto& v : b) {
                        float val = v.get<float>();
                        if (npts % 2 == 0) sum_x += val;
                        else sum_y += val;
                        npts += 1;
                    }
                    o.cx = sum_x / (npts / 2.0f);
                    o.cy = sum_y / (npts / 2.0f);
                    texts.push_back(o);
                }
                for (auto& c : cells) {
                    float ox1 = c.box[0] * src_w, oy1 = c.box[1] * src_h;
                    float ox2 = c.box[2] * src_w, oy2 = c.box[3] * src_h;
                    std::vector<std::string> inside;
                    for (const auto& o : texts) {
                        if (o.cx >= ox1 && o.cx <= ox2 && o.cy >= oy1 &&
                            o.cy <= oy2) {
                            inside.push_back(o.text);
                        }
                    }
                    std::ostringstream oss;
                    for (size_t i = 0; i < inside.size(); ++i) {
                        if (i) oss << " ";
                        oss << inside[i];
                    }
                    c.text = oss.str();
                }
            }
        }
        auto t6 = Clock::now();

        write_outputs(md_path, json_path, cells, nrows, ncols);

        std::cout << "rows=" << nrows << " cols=" << ncols
                  << " cells=" << cells.size() << "\n";
        std::cout << "preprocess_ms=" << ms(t0, t1)
                  << "\nencoder_ms=" << ms(t1, t2)
                  << "\ndecoder_ms=" << ms(t2, t3)
                  << "\nbbox_ms=" << ms(t3, t4)
                  << "\nstruct_ms=" << ms(t4, t5)
                  << "\nocr_ms=" << ms(t5, t6)
                  << "\ntotal_ms=" << ms(t0, t6) << "\n";
        std::cout << "tokens:";
        for (int t : seq) std::cout << " " << TOK.at(t);
        std::cout << "\n";
    } catch (const std::exception& e) {
        std::cerr << "ERROR: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
