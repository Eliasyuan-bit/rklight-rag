#!/usr/bin/env python3
"""Group streamed footer entries by upload, preserving chunk-level API data."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_DOCUMENT_REFERENCE_FOOTER_V1"
IMPORT_ANCHOR = "    build_reference_preview, render_reference_document, valid_chunk_id,\n"
IMPORT_INSERT = (
    "    build_reference_preview, group_footer_references,\n"
    "    render_reference_document, valid_chunk_id,\n"
    + MARKER + "\n"
)
STREAM_ANCHOR = "reference_footer = render_reference_markdown(references)"
STREAM_INSERT = "reference_footer = render_reference_markdown(await group_footer_references(references, rag))"
NONSTREAM_ANCHOR = "response_content += render_reference_markdown(references)"
NONSTREAM_INSERT = "response_content += render_reference_markdown(await group_footer_references(references, rag))"


def install(path: Path) -> None:
    source = path.read_text()
    if MARKER in source:
        print(f"already installed: {path}")
        return
    for anchor in (IMPORT_ANCHOR, STREAM_ANCHOR, NONSTREAM_ANCHOR):
        if source.count(anchor) != 1:
            raise SystemExit(f"unsupported LightRAG source: expected one {anchor!r}")
    backup = path.with_suffix(path.suffix + ".before-rk3588-document-reference-footer")
    if not backup.exists():
        backup.write_text(source)
    source = source.replace(IMPORT_ANCHOR, IMPORT_INSERT, 1)
    source = source.replace(STREAM_ANCHOR, STREAM_INSERT, 1)
    source = source.replace(NONSTREAM_ANCHOR, NONSTREAM_INSERT, 1)
    path.write_text(source)
    print(f"installed: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    install(parser.parse_args().path)
