# PDFium dependency

Do not commit PDFium headers or binaries to this repository. The build expects:

```text
$PDFIUM_ROOT/
  include/fpdfview.h
  include/fpdf_text.h
  lib/libpdfium.so
```

For initial RK3588 validation, run `scripts/prepare-pdfium-arm64.sh`. It pins
an arm64 `pypdfium2` wheel, whose bundled PDFium binary originates from
`pdfium-binaries`, then copies PDFium's public C headers. The C++ service has
no Python runtime dependency. Retain the generated `licenses/` directory when
redistributing the runtime package. For production, build and pin PDFium from
its Chromium source revision.
