# TableFormer CPU 表格解析工具

## 一、概述

`tools/tableformer_cpu` 是一个在 RK3588 CPU 上运行的独立 ARM64 命令行程序。它用 ONNX
Runtime 跑通 TableFormer 的 encoder、decoder 和 bbox decoder，并调用板端已有的
PPOCRv6 服务补全单元格文字，最终输出 Markdown 表格和结构化的 `cells.json`。

TableFormer 本体不依赖 RK1828 的 NPU，整个结构推理链路都在 RK3588 CPU 上完成，适合作为
“单张表格图片 → 结构化结果”的离线解析入口。混合内容 PDF 入口使用板端 Python 3 与 Pillow
做编排和无损裁剪，并复用现有 Document Vision、DocLayout-YOLO 与 PPOCRv6 服务。

## 二、整体流程

```text
图片
  -> 读取并缩放到 448x448
  -> encoder.onnx    (cross_k / cross_v / enc_out)
  -> decoder.onnx    (自回归生成 OTSL 结构 + 收集 cell hidden)
  -> bbox.onnx       (单元格框 boxes + 类别 classes)
  -> ppocrv6_ocr_daemon (整图 OCR)
  -> 按单元格框匹配 OCR 文本
  -> Markdown + cells.json
```

各阶段耗时会被打印出来，便于定位瓶颈：

```text
preprocess_ms / encoder_ms / decoder_ms / bbox_ms / struct_ms / ocr_ms / total_ms
```

## 三、模型接口

三个 ONNX 模型来自 TableFormer，接口如下：

### encoder.onnx

```text
输入:
  image          [1, 3, 448, 448]

输出:
  cross_k        [6, 1, 8, 784, 64]
  cross_v        [6, 1, 8, 784, 64]
  enc_out        [1, 28, 28, 256]   # NHWC，供 bbox 使用
  cross_kt_0..5  [1, 8, 64, 784]
  cross_v_0..5   [1, 8, 784, 64]
```

### decoder.onnx

```text
输入:
  tags           [seq, 1]           # 完整前缀 token 序列
  cross_k        [6, 1, 8, 784, 64]
  cross_v        [6, 1, 8, 784, 64]
  cache          [6, past, 1, 512]

输出:
  logits         [1, 13]
  hidden         [1, 512]           # 最后一个输入 token 的隐藏状态
  out_cache      [6, past+1, 1, 512]
```

解码时每次传入完整前缀，直到生成 `<end>`（或达到 `max_steps`）。

### bbox.onnx

```text
输入:
  enc_out        [1, 28, 28, 256]   # encoder 的 enc_out
  tag_h          [ncells, 512]      # 每个单元格收集到的 hidden

输出:
  boxes          [ncells, 4]        # cxcywh，归一化，模型内已做 sigmoid
  classes        [ncells, 3]        # 原始 logits，取 argmax
```

## 四、OTSL 标签

decoder 的 13 类标签为：

| id | 标签 | 含义 |
| --- | --- | --- |
| 0 | `<pad>` | 填充 |
| 1 | `<unk>` | 未知 |
| 2 | `<start>` | 起始 |
| 3 | `<end>` | 结束 |
| 4 | `ecel` | 空单元格 |
| 5 | `fcel` | 普通单元格 |
| 6 | `lcel` | 横向合并的延续单元格 |
| 7 | `ucel` | 纵向合并的延续单元格 |
| 8 | `xcel` | 二维合并的延续单元格 |
| 9 | `nl` | 换行 |
| 10 | `ched` | 列头 |
| 11 | `rhed` | 行头 |
| 12 | `srow` | 行分区 |

## 五、目录结构

```text
tools/tableformer_cpu/
├── CMakeLists.txt
├── README.md
├── cmake/
│   └── aarch64-linux-gnu.cmake
├── scripts/
│   ├── build.sh          # 交叉编译
│   ├── deploy_162.sh     # 通过 162 部署到 RK3588
│   ├── run.sh            # 板端运行脚本
│   ├── run_pdf.sh        # 混合内容 PDF 一键入口
│   ├── pdf_table_parse.py# PDF 版面/裁剪/回填编排
│   └── test_162.sh       # 一键测试并拉回结果
├── src/
│   └── main.cc
├── testdata/
│   └── simple_table.svg
└── third_party/
    ├── nlohmann/         # JSON 解析（解析 OCR daemon 返回）
    └── stb/              # 图片读取与缩放
```

## 六、构建与部署

主机 191 上交叉编译：

```bash
cd tools/tableformer_cpu
./scripts/build.sh
```

产物为 `out/tableformer_cpu/`，包含可执行文件、`libonnxruntime.so` 软链和 `run.sh`。

部署到 162 所连接的 RK3588：

```bash
./scripts/deploy_162.sh
```

部署目录为板端 `/userdata/tableformer_cpu`，模型在 `/userdata/tableformer_cpu/models`。

一键测试（推送示例图、运行、拉回 Markdown）：

```bash
./scripts/test_162.sh
```

结果写到 `tools/tableformer_cpu/out/output.md`。

## 七、运行

板端运行：

```bash
cd /userdata/tableformer_cpu
./run.sh /userdata/table.png /userdata/table.md 256
```

参数含义：

```text
tableformer_cpu IMAGE OUTPUT.md [encoder.onnx] [decoder.onnx] [bbox.onnx] [max_steps]
```

同时生成：

```text
/userdata/table.md
/userdata/table.md.cells.json
```

`cells.json` 是单元格数组，包含：

```json
{
  "id": 0,
  "row": 0,
  "col": 0,
  "row_span": 1,
  "col_span": 1,
  "label": "ched",
  "class": 2,
  "bbox": [0.0706, 0.1117, 0.1820, 0.2267],
  "text": "Model"
}
```

其中 `bbox` 是归一化到输入图的 `[x1, y1, x2, y2]`。

### 混合内容 PDF

```bash
cd /userdata/tableformer_cpu
./run_pdf.sh /userdata/document.pdf /userdata/document-output
```

处理过程为：

```text
PDF
  -> Document Vision（PDFium 文本层 + DocLayout-YOLO）
  -> 只渲染含 table 区域的页面
  -> 按 layout bbox 裁剪表格
  -> TableFormer 结构与 bbox
  -> 有文本层时按 bbox 回填 PDFium 原生字符；否则保留 PPOCRv6 文字
  -> 将表格回填到原页面阅读顺序
  -> document.md + document.json + tables/*
```

主要输出：

| 文件 | 内容 |
| --- | --- |
| `document.md` | 正文和 Markdown 表格按页面阅读顺序合并后的结果 |
| `document.json` | 页面块、TableFormer 行列、cell bbox 和页坐标 |
| `document.raw.md/json` | TableFormer 处理前的无损基线，供降级和审计 |
| `tables/*.md` | 每个表格的独立 Markdown |
| `tables/*.md.cells.json` | 每个表格的原始 cell 结果 |
| `tableformer-summary.json` | 页数、表格成功数、失败数和总耗时 |

单个表格解析失败时标记为 `fallback`，保留原始 PDFium/OCR 文本；不会因为一个异常表格丢掉
整份 PDF。LightRAG 的 RKVision 适配器会优先读取 `status=ok` 的 TableFormer 网格，并用
`page_box` 保留每个单元格的引用位置。

## 八、OCR 配置

OCR 默认调用板端已有的 `ppocrv6_ocr_daemon`：

```text
/userdata/ppocrv6-rknn-service/bin/ppocrv6_ocr_daemon
/userdata/ppocrv6-rknn-service/models
/userdata/ppocrv6-rknn-service/lib
```

可通过环境变量覆盖或关闭：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `TF_OCR_DAEMON` | `/userdata/ppocrv6-rknn-service/bin/ppocrv6_ocr_daemon` | OCR 可执行文件 |
| `TF_OCR_MODELS` | `/userdata/ppocrv6-rknn-service/models` | OCR 模型目录 |
| `TF_OCR_LIB` | `/userdata/ppocrv6-rknn-service/lib` | OCR 动态库目录 |
| `TF_OCR_DISABLE` | 未设置 | 设为 `1` 时关闭 OCR，只输出结构 |

## 九、关键实现细节

### 图片预处理转置

参考 TableFormer 实现会把缩放后的图像按通道做一次 H/W 交换后送入模型。旧实现漏掉这一步，
导致表格方向被识别成转置结果（例如 5 行 3 列被识别成 3 行 5 列）。当前代码按：

```cpp
pix[c * 448 * 448 + x * 448 + y] =
    (im[(y * 448 + x) * 3 + c] / 255.0f - mean[c]) / sd[c];
```

与参考实现保持一致，表格方向和列头（`ched`）识别均正确。

### cell hidden 收集

decoder 每步输出 `hidden` 是“最后一个输入 token”的隐藏状态。程序按参考实现的状态机，在
生成 `fcel/ecel/ched/rhed/srow/nl/ucel` 以及横向合并的 `lcel` 时收集对应 hidden，得到
`tag_h [ncells,512]`，再送入 bbox。

### bbox span 合并

横向合并（`fcel + lcel...`）会生成首尾两个框，程序按参考实现把二者合并成一个 span 框。

### OCR 文本匹配

OCR 在原始输入图上运行，得到文本框。每个单元格的归一化 bbox 会被映射回原始图坐标，文本
框中心落在单元格内的文本按顺序拼接为该单元格内容。

### PDF 原生字符回填

Document Vision 会在 `document.json` 中输出 `native_glyphs`，每个可见字符包含原文、页坐标
和字符前是否存在原始空格。PDF 表格处理完成后，单元格 bbox 被映射回页面坐标，原生字符按
坐标分配给对应单元格。只要单元格存在原生字符，就用 PDFium 文本替换 OCR，并保留
`ocr_text` 供审计；扫描件或无文本层的单元格继续使用 OCR。

正文重排同样保留 PDF 文本层中的显式空格，不再只靠字符几何间距猜测英文单词边界。

## 十、验证结果

示例图 `testdata/simple_table.svg` 在 RK3588 上实测：

```text
rows=5 cols=3 cells=15
encoder_ms=869.6  decoder_ms=430.4  bbox_ms=260.1  ocr_ms=654.2  total_ms=2226.0
```

输出 Markdown：

```markdown
| Model | TTFT (ms) | TPS |
| --- | --- | --- |
| Qwen2.5-7B | 162.25 | 70.47 |
| Qwen3-4B | 88.47 | 91.30 |
| Qwen3.5-2B | 79.32 | 91.40 |
| Qwen3.5-4B | 160.56 | 50.86 |
```

混合 PDF `00_Rockchip_RKNPU3_ReleaseNote_RKNN3_SDK_V1.0.4_EN.pdf` 实测：

```text
page_count=14
table_count=12
success_count=12
failure_count=0
elapsed_ms=70084.657   # 复用已有 Document Vision JSON
```

其中第 9 页 LLM 性能表恢复为 9 行 7 列，第 9 页 VLM 性能表恢复为 11 行 6 列；
`Qwen2.5-7B` 的 `162.25 / 14.19 / 70.47` 和 `Qwen3-4B` 的
`109.78 / 11.30 / 88.47` 均落入正确列。

## 十一、已知限制

- TableFormer 本体只负责表格结构和单元格位置。原生文本 PDF 使用 PDFium 字符，扫描件使用
  OCR，因此扫描件仍可能出现字符误识别。
- 二维合并（`xcel`）的 span 处理沿用参考实现的简化版本，复杂跨行列合并仍有边界情况需要
  进一步验证。
- 跨页续表当前按页保留为多个表格，尚未自动判断并合并相邻页面上表头一致的续表。
