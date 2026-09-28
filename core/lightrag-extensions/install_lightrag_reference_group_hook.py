#!/usr/bin/env python3
"""Enrich reference previews with an exact upload-group identity."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_REFERENCE_GROUP_V1"
ANCHOR = '''        return build_reference_preview(chunk_id, chunk)
'''
INSERT = '''        full_doc_id = str(chunk.get("full_doc_id") or "")
        doc_status = await rag.doc_status.get_by_id(full_doc_id) if full_doc_id else None
        # RK3588_REFERENCE_GROUP_V1
        return build_reference_preview(chunk_id, chunk, doc_status)
'''


def install(path: Path) -> None:
    source = path.read_text()
    if MARKER in source:
        print(f"already installed: {path}")
        return
    if source.count(ANCHOR) != 1:
        raise SystemExit("unsupported LightRAG source: reference preview route missing")
    backup = path.with_suffix(path.suffix + ".before-rk3588-reference-group")
    if not backup.exists():
        backup.write_text(source)
    path.write_text(source.replace(ANCHOR, INSERT, 1))
    print(f"installed: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    install(parser.parse_args().path)
