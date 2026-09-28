#!/usr/bin/env python3
"""Install chunk-level reference IDs into the pinned LightRAG source."""
from __future__ import annotations

import argparse
from pathlib import Path


UTILS_MARKER = "# RK3588_CHUNK_CITATIONS_V1"
UTILS_IMPORT_ANCHOR = (
    "from lightrag.exceptions import ChunkBlockMatchError, EmptyTruncatedResponseError\n"
)
UTILS_IMPORT_INSERT = UTILS_IMPORT_ANCHOR + (
    "from lightrag.rk_chunk_citations import generate_chunk_reference_list\n"
)
UTILS_OVERRIDE_ANCHOR = "def render_chunks_context_text(chunks_with_reference_ids: list[dict]) -> str:\n"
UTILS_OVERRIDE_INSERT = '''# RK3588_CHUNK_CITATIONS_V1
_generate_file_reference_list_from_chunks = generate_reference_list_from_chunks


def generate_reference_list_from_chunks(
    chunks: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Generate one reference per retained evidence chunk."""
    return generate_chunk_reference_list(chunks)


def render_chunks_context_text(chunks_with_reference_ids: list[dict]) -> str:
'''

ROUTES_MARKER = "# RK3588_CHUNK_CITATION_FIELDS_V1"
ROUTES_ANCHOR = '''    file_path: str = Field(description="Path to the source file")
    content: Optional[List[str]] = Field(
'''
ROUTES_INSERT = '''    file_path: str = Field(description="Path to the source file")
    chunk_id: Optional[str] = Field(
        default=None,
        description="Exact evidence chunk identifier",
    )
    section: Optional[str] = Field(
        default=None,
        description="Markdown section containing the evidence",
    )
    # RK3588_CHUNK_CITATION_FIELDS_V1
    content: Optional[List[str]] = Field(
'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise SystemExit(
            f"unsupported LightRAG source; expected one {label}, got {source.count(old)}"
        )
    return source.replace(old, new, 1)


def install_utils(path: Path) -> None:
    source = path.read_text()
    if UTILS_MARKER in source:
        print(f"already installed: {path}")
        return
    backup = path.with_suffix(path.suffix + ".before-rk3588-chunk-citations")
    if not backup.exists():
        backup.write_text(source)
    source = replace_once(source, UTILS_IMPORT_ANCHOR, UTILS_IMPORT_INSERT, "utils import")
    source = replace_once(
        source, UTILS_OVERRIDE_ANCHOR, UTILS_OVERRIDE_INSERT, "reference override"
    )
    path.write_text(source)
    print(f"installed: {path}")


def install_routes(path: Path) -> None:
    source = path.read_text()
    if ROUTES_MARKER in source:
        print(f"already installed: {path}")
        return
    backup = path.with_suffix(path.suffix + ".before-rk3588-chunk-citations")
    if not backup.exists():
        backup.write_text(source)
    source = replace_once(source, ROUTES_ANCHOR, ROUTES_INSERT, "reference schema")
    path.write_text(source)
    print(f"installed: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("utils_path", type=Path)
    parser.add_argument("query_routes_path", type=Path)
    args = parser.parse_args()
    install_utils(args.utils_path)
    install_routes(args.query_routes_path)


if __name__ == "__main__":
    main()
