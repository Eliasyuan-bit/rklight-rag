#!/usr/bin/env python3
"""Install source-authority adjustment after LightRAG reranking."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_SOURCE_AUTHORITY_V2"
OLD_MARKER = "# RK3588_SOURCE_AUTHORITY_V1"
IMPORT_ANCHOR = (
    "from lightrag.exceptions import ChunkBlockMatchError, EmptyTruncatedResponseError\n"
)
IMPORT_INSERT = IMPORT_ANCHOR + (
    "from lightrag.rk_source_policy import apply_source_authority_policy\n"
)
RERANK_TRACE_ANCHOR = '''        _rk_log_chunk_stage(
            query,
            "reranked",
'''
RERANK_TRACE_INSERT = '''        unique_chunks = apply_source_authority_policy(unique_chunks, query)
        logger.info(
            "Source authority policy: adjusted=%d/%d",
            sum(1 for chunk in unique_chunks if chunk.get("source_penalty", 1.0) < 1.0),
            len(unique_chunks),
        )
        # RK3588_SOURCE_AUTHORITY_V2
        _rk_log_chunk_stage(
            query,
            "reranked",
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
    if OLD_MARKER in source:
        source = replace_once(
            source,
            "apply_source_authority_policy(unique_chunks)",
            "apply_source_authority_policy(unique_chunks, query)",
            "v1 source policy call",
        )
        source = source.replace(OLD_MARKER, MARKER, 1)
        path.write_text(source)
        print(f"upgraded: {path}")
        return
    backup = path.with_suffix(path.suffix + ".before-rk3588-source-policy")
    if not backup.exists():
        backup.write_text(source)
    source = replace_once(source, IMPORT_ANCHOR, IMPORT_INSERT, "utils import")
    source = replace_once(
        source, RERANK_TRACE_ANCHOR, RERANK_TRACE_INSERT, "rerank trace"
    )
    path.write_text(source)
    print(f"installed: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    install(args.path)


if __name__ == "__main__":
    main()
