# Document Vision Service

Local, native page-parser orchestration for RK3588 document ingestion. It
combines three already-local components without duplicating their models:

```text
PDF ── PDFium ── rendered page ── DocLayout-YOLO ── page regions
       │                                      │
       └── character boxes ───────────────────┘
                                                │
                       region text: PDFium when sufficient; PPOCRv6 otherwise
                                                │
                                             page JSON
```

This is deliberately a region-level decision. A native PDF text layer can be
present yet incomplete or have unusable reading order; `usable=true` from the
PDFium probe is only diagnostic and never suppresses OCR for the whole page.

## Build dependency

Provide an aarch64 PDFium distribution through `PDFIUM_ROOT`:

```text
PDFIUM_ROOT/
  include/fpdfview.h
  include/fpdf_text.h
  lib/libpdfium.so
```

To prepare this directory for initial RK3588 validation:

```bash
PDFIUM_HEADERS_REPOSITORY=git@github.com:chromium/pdfium.git \
  ./scripts/prepare-pdfium-arm64.sh /path/to/pdfium-linux-arm64
```

The script pins an arm64 `pypdfium2` wheel, whose bundled PDFium binary is
provided by [pdfium-binaries](https://github.com/bblanchon/pdfium-binaries),
and copies the upstream public C headers. The native runtime does not depend on
Python. Pin and preserve the resulting `VERSION` and `licenses/` files before
production distribution.

## Cross build

```bash
export RK3588_SDK_ROOT=/path/to/rockchip-sdk
export PDFIUM_ROOT=/path/to/pdfium-linux-arm64
export PPOCR_SERVICE_ROOT=/path/to/ppocrv6-rknn-service
export DOCLAYOUT_SERVICE_ROOT=/path/to/doclayout-yolo-rknn-service
./scripts/build-rk3588.sh
```

`PPOCR_SERVICE_ROOT` and `DOCLAYOUT_SERVICE_ROOT` must contain the respective
already-built RKNN core libraries. Their models are not copied into this
package.

## PDFium page verification

```bash
./dist/rk3588/bin/pdfium_page \
  --input document.pdf --page 1 \
  --text page-001.txt \
  --render page-001.png --dpi 200
```

`--text` validates direct extraction of a native PDF text layer. `--render`
generates a BGR page image for the visual route. The module prints a
conservative `usable=true/false` signal for observability only.

## Page parser

On the board, reuse the existing PPOCRv6 and DocLayout-YOLO model locations:

```bash
export LD_LIBRARY_PATH=/userdata/document-vision-service/lib

/userdata/document-vision-service/bin/pdf_page_parse \
  --input /userdata/document-vision-service/input/sample.pdf \
  --page 1 \
  --layout-model /userdata/doclayout-yolo-rknn-service/models/doclayout_yolo_640_logits_i8.rknn \
  --ocr-models /models \
  --dict /userdata/ppocrv6-rknn-service/ppocrv6_dict.txt \
  --dpi 200 \
  --output /userdata/document-vision-service/output/page-001.json
```

`native_text` is always the complete PDFium page extraction and is the
lossless text-layer fallback. PPOCRv6 always runs on the complete rendered
page and creates the line-level `blocks`; it is never gated by Layout. Each
block has original rendered-page pixel coordinates, a semantic Layout label
when one overlaps it, text and `text_source` (`pdfium`, `ocr`, or `none`). A
PDF character is assigned to at most one OCR box; characters not covered by
any OCR box are emitted as `unassigned_native_text` blocks. DocLayout-YOLO
results are emitted separately in `layout_regions`, so a missed or overlapping
`figure` region cannot erase text.

`--min-native-characters` defaults to `4`; increasing it is useful for
validating or tuning the OCR fallback, not as a global PDF-text switch.

For a page with at least 80 non-whitespace PDFium characters, the default
route is `pdfium_native`: it skips rendering, Layout and OCR entirely and
reconstructs the reading order from native glyph coordinates. Sparse or
scanned pages use `vision_fusion`, the full PDFium + Layout + PPOCR path.
`parse_route` is emitted in each page JSON for observability.

## Long-running document service

`pdf_page_parse` is a page-level diagnostic tool. For ingestion, run one
`document_vision_daemon` process. It initializes PDFium, DocLayout-YOLO and
PPOCRv6 once at startup; each JSONL request then parses a whole PDF
sequentially with those same RKNN contexts.

```bash
export LD_LIBRARY_PATH=/userdata/document-vision-service/lib
/userdata/document-vision-service/bin/document_vision_daemon \
  --layout-model /userdata/doclayout-yolo-rknn-service/models/doclayout_yolo_640_logits_i8.rknn \
  --ocr-models /models \
  --dict /userdata/ppocrv6-rknn-service/ppocrv6_dict.txt \
  --dpi 200
```

Write one request per line to its standard input:

```json
{"id":"smart-cabinet-001","input":"/userdata/document-vision-service/input/smart-cabinet-guide.pdf","output_dir":"/userdata/document-vision-service/output/smart-cabinet-001"}
```

After all models are initialized, the daemon emits `{"ready":true}`. Measure
per-document latency from submitting a request after this event to the matching
response; its `elapsed_ms` excludes startup/model initialization.

The response is compact and includes only status, page count, output path and
request-only `elapsed_ms` (model initialization is excluded). The result
directory contains:

```text
smart-cabinet-001/
  document.md          # reading-order text for the LightRAG parser path
  document.json        # complete merged, lossless structured result
  pages/page-001.json  # per-page geometry, OCR scores and text provenance
  pages/page-002.json
  ...
```

`document.md` is deliberately plain reading-order text. `document.json` and
the page files retain OCR polygons, OCR confidence, PDFium source text and
layout metadata for later auditing or a richer Markdown reconstruction.

When producing `document.md`, an OCR-only block whose DocLayout-YOLO class is
`figure` is omitted from the reading stream. This prevents screenshot/UI OCR
noise from entering RAG chunks. The block is still present in `document.json`
with its geometry and confidence. PDFium text is never removed by this rule;
tables are also retained for a later table-specific renderer.

## ADB deployment

After cross-building on the host, deploy only this module's binary and shared
libraries. The script does not overwrite the separately versioned OCR/layout
services or their model files.

```bash
ADB_SERIAL=<serial> ./scripts/deploy-adb.sh
```
