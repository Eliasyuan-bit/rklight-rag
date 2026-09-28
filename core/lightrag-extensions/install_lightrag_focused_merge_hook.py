#!/usr/bin/env python3
"""Preserve bounded lexical passages across LightRAG mixed chunk merging."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_FOCUSED_MERGE_V2"
OLD_MARKER = "# RK3588_FOCUSED_MERGE_V1"
IMPORT_ANCHOR = "# RK3588_LEXICAL_CHUNK_RETRIEVAL_V1\n"
IMPORT_INSERT = IMPORT_ANCHOR + (
    "from lightrag.rk_lexical_retrieval import (\n"
    "    bound_mix_graph_chunks,\n"
    "    preserve_focused_evidence,\n"
    ")\n"
    "# RK3588_FOCUSED_MERGE_V2\n"
)
OLD_IMPORT = (
    "from lightrag.rk_lexical_retrieval import preserve_focused_evidence\n"
    "# RK3588_FOCUSED_MERGE_V1\n"
)
CAP_ANCHOR = '''    # Round-robin merge chunks from different sources with deduplication
'''
CAP_INSERT = '''    uncapped_entity_chunks = len(entity_chunks)
    uncapped_relation_chunks = len(relation_chunks)
    entity_chunks, relation_chunks = bound_mix_graph_chunks(
        entity_chunks, relation_chunks, query_param
    )
    if (
        len(entity_chunks) != uncapped_entity_chunks
        or len(relation_chunks) != uncapped_relation_chunks
    ):
        logger.info(
            "Mix graph chunk cap: entities %d->%d, relations %d->%d",
            uncapped_entity_chunks,
            len(entity_chunks),
            uncapped_relation_chunks,
            len(relation_chunks),
        )

    # Round-robin merge chunks from different sources with deduplication
'''
MERGE_ANCHOR = '''    logger.info(
        f"Round-robin merged chunks: {origin_len} -> {len(merged_chunks)} (deduplicated {origin_len - len(merged_chunks)})"
    )
'''
MERGE_INSERT = '''    restored_focused = preserve_focused_evidence(merged_chunks, vector_chunks)
    logger.info(
        f"Round-robin merged chunks: {origin_len} -> {len(merged_chunks)} "
        f"(deduplicated {origin_len - len(merged_chunks)}, focused restored {restored_focused})"
    )
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
    backup = path.with_suffix(path.suffix + ".before-rk3588-focused-merge")
    if not backup.exists():
        backup.write_text(source)
    if OLD_MARKER in source:
        source = replace_once(source, OLD_IMPORT, IMPORT_INSERT, "v1 import")
    else:
        source = replace_once(source, IMPORT_ANCHOR, IMPORT_INSERT, "lexical marker")
        source = replace_once(source, MERGE_ANCHOR, MERGE_INSERT, "round-robin log")
    source = replace_once(source, CAP_ANCHOR, CAP_INSERT, "mixed chunk merge")
    path.write_text(source)
    print(f"installed: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    install(args.path)


if __name__ == "__main__":
    main()
