#!/usr/bin/env python3
"""Restore typed table locations at LightRAG's final query API boundary."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_REFERENCE_LOCATION_V1"
IMPORT_ANCHOR = "from lightrag.rk_reference_markdown import render_reference_markdown\n"
IMPORT_INSERT = (
    IMPORT_ANCHOR
    + "from lightrag.rk_chunk_citations import enrich_reference_locations\n"
    + MARKER
    + "\n"
)
NONSTREAM_ANCHOR = '''                references = enriched_references

            # Return response with or without references based on request
'''
NONSTREAM_INSERT = '''                references = enriched_references

            references = enrich_reference_locations(
                references, data.get("chunks", []), request.query
            )

            # Return response with or without references based on request
'''
STREAM_SIGNATURE_ANCHOR = '''        include_chunk_content: bool,
        include_response_time: bool,
'''
STREAM_SIGNATURE_INSERT = '''        include_chunk_content: bool,
        include_response_time: bool,
        query: str,
'''
STREAM_ANCHOR = '''                references = enriched_references

            if llm_response.get("is_streaming"):
'''
STREAM_INSERT = '''                references = enriched_references

            references = enrich_reference_locations(
                references, result.get("data", {}).get("chunks", []), query
            )

            if llm_response.get("is_streaming"):
'''
CALL_ANCHOR = '''                            include_response_time=True,
                            start_time=start_time,
'''
CALL_INSERT = '''                            include_response_time=True,
                            query=request.query,
                            start_time=start_time,
'''
DEFAULT_CALL_ANCHOR = '''                    include_response_time=False,
                    start_time=start_time,
'''
DEFAULT_CALL_INSERT = '''                    include_response_time=False,
                    query=request.query,
                    start_time=start_time,
'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise SystemExit(
            f"unsupported LightRAG source; expected one {label}, got {source.count(old)}"
        )
    return source.replace(old, new, 1)


def install(path: Path) -> None:
    source = path.read_text()
    if MARKER in source:
        print(f"already installed: {path}")
        return
    backup = path.with_suffix(path.suffix + ".before-rk3588-reference-location")
    if not backup.exists():
        backup.write_text(source)
    source = replace_once(source, IMPORT_ANCHOR, IMPORT_INSERT, "reference location import")
    source = replace_once(source, NONSTREAM_ANCHOR, NONSTREAM_INSERT, "non-stream reference boundary")
    source = replace_once(source, STREAM_SIGNATURE_ANCHOR, STREAM_SIGNATURE_INSERT, "stream signature")
    source = replace_once(source, STREAM_ANCHOR, STREAM_INSERT, "stream reference boundary")
    source = replace_once(source, CALL_ANCHOR, CALL_INSERT, "progress stream call")
    source = replace_once(source, DEFAULT_CALL_ANCHOR, DEFAULT_CALL_INSERT, "default stream call")
    path.write_text(source)
    print(f"installed: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    install(args.path)


if __name__ == "__main__":
    main()
