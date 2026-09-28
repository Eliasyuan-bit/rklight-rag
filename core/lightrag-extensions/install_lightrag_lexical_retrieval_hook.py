#!/usr/bin/env python3
"""Install board-local lexical chunk retrieval into pinned LightRAG source."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_LEXICAL_CHUNK_RETRIEVAL_V2"
OLD_MARKER = "# RK3588_LEXICAL_CHUNK_RETRIEVAL_V1"
IMPORT_ANCHOR = "from lightrag.prompt import PROMPTS, resolve_entity_extraction_prompt_profile\n"
IMPORT_INSERT = '''from lightrag.prompt import PROMPTS, resolve_entity_extraction_prompt_profile
from lightrag.rk_lexical_retrieval import (
    fuse_vector_and_lexical_chunks,
    retrieval_candidate_k,
)
# RK3588_LEXICAL_CHUNK_RETRIEVAL_V2
'''
QUERY_ANCHOR = '''    results = await chunks_vdb.query(
        query, top_k=search_top_k, query_embedding=query_embedding
    )
'''
QUERY_INSERT = '''    candidate_top_k = retrieval_candidate_k(search_top_k, query)
    results = await chunks_vdb.query(
        query, top_k=candidate_top_k, query_embedding=query_embedding
    )
'''
RETURN_ANCHOR = '''    logger.info(
        f"Naive query: {len(valid_chunks)} chunks (chunk_top_k:{search_top_k} cosine:{cosine_threshold})"
    )
    return valid_chunks
'''
RETURN_INSERT = '''    valid_chunks = await fuse_vector_and_lexical_chunks(
        query, valid_chunks, chunks_vdb.global_config, search_top_k
    )
    logger.info(
        f"Naive query: {len(valid_chunks)} candidate chunks "
        f"(chunk_top_k:{search_top_k} candidate_top_k:{candidate_top_k} cosine:{cosine_threshold})"
    )
    return valid_chunks
'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise SystemExit(f"unsupported LightRAG source; expected one {label}, got {source.count(old)}")
    return source.replace(old, new, 1)


def install(path: Path) -> None:
    source = path.read_text()
    if MARKER in source:
        print(f"already installed: {path}")
        return
    if OLD_MARKER in source:
        old_call = "candidate_top_k = retrieval_candidate_k(search_top_k)"
        if source.count(old_call) != 1:
            raise SystemExit(
                "unsupported LightRAG source; expected one v1 candidate call"
            )
        source = source.replace(
            old_call,
            "candidate_top_k = retrieval_candidate_k(search_top_k, query)",
            1,
        ).replace(OLD_MARKER, MARKER, 1)
        path.write_text(source)
        print(f"upgraded: {path}")
        return
    backup = path.with_suffix(path.suffix + ".before-rk3588-lexical-retrieval")
    if not backup.exists():
        backup.write_text(source)
    source = replace_once(source, IMPORT_ANCHOR, IMPORT_INSERT, "import anchor")
    source = replace_once(source, QUERY_ANCHOR, QUERY_INSERT, "vector query")
    source = replace_once(source, RETURN_ANCHOR, RETURN_INSERT, "vector result return")
    path.write_text(source)
    print(f"installed: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    install(args.path)


if __name__ == "__main__":
    main()
