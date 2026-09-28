# TableFormer CPU for RK3588

This project cross-compiles a standalone ARM64 command-line program that runs
the TableFormer encoder, dynamic decoder, and cell bbox decoder with ONNX
Runtime on the RK3588 CPU. It prints preprocessing, encoder, decoder, bbox,
structure, OCR, and total latency.

完整的设计、模型接口、配置与验证说明见 [docs/tableformer-cpu.md](../../docs/tableformer-cpu.md)。

The program now runs end to end:

```text
image
  -> encoder.onnx (cross_k/cross_v + enc_out)
  -> decoder.onnx (autoregressive OTSL structure + cell hidden states)
  -> bbox.onnx (cell boxes + classes)
  -> ppocrv6 OCR daemon (cell text)
  -> Markdown + cells.json
```

For standalone images, cell text is obtained by spawning the board-side
`ppocrv6_ocr_daemon` and matching its detected text boxes against each
predicted cell box. For native-text PDFs, PDFium glyphs replace OCR text after
their page coordinates are assigned to the predicted cells. OCR can be
disabled with `TF_OCR_DISABLE=1`; the daemon/models/library paths default to
`/userdata/ppocrv6-rknn-service` and can be overridden with `TF_OCR_DAEMON`,
`TF_OCR_MODELS`, and `TF_OCR_LIB`.

The image is resized to 448x448 and fed with the channel transpose used by the
reference TableFormer implementation, so table orientation and header cells are
decoded correctly.

Build on host 191:

```bash
cd tools/tableformer_cpu
./scripts/build.sh
```

Deploy through host 162 to the RK3588 board:

```bash
./scripts/deploy_162.sh
```

Run on the board:

```bash
cd /userdata/tableformer_cpu
./run.sh /userdata/table.png /userdata/table.md 256
```

Parse a mixed-content PDF end to end:

```bash
./run_pdf.sh /userdata/release-note.pdf /userdata/release-note-output
```

This uses the existing Document Vision service to locate table regions, runs
TableFormer only on those crops, and writes an enriched `document.md` and
`document.json`. A failed individual table keeps its original page text rather
than failing the complete document.

The same invocation also writes `/userdata/table.md.cells.json` containing each
cell's row, column, spans, class, normalized bbox, and recognized text.

For a quick smoke test, use a small limit such as `8` before running the full
decoder:

```bash
./run.sh /userdata/table.png /userdata/table.md 8
```

Or run the included table fixture from host 191 and pull the Markdown result
back into `out/output.md`:

```bash
./scripts/test_162.sh
```
