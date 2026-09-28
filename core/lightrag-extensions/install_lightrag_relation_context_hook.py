#!/usr/bin/env python3
"""Ground relation-fact answers in source chunks after graph retrieval."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_RELATION_CONTEXT_V1"
ANCHOR = '''    tokenizer = global_config.get("tokenizer")
'''
INSERT = '''    # Graph entities and relations have already been used to expand and merge
    # candidate chunks at this point.  For a relation-fact query, ground the
    # small answer model in those original chunks instead of also rendering
    # broad KG summaries that can override the source evidence.
    from lightrag.rk_lexical_retrieval import query_retrieval_profile
    if merged_chunks and query_retrieval_profile(query) == "relation_fact":
        logger.info(
            "Relation-fact answer grounding: suppressing %d entities and %d "
            "relations after graph-guided chunk retrieval",
            len(entities_context),
            len(relations_context),
        )
        entities_context = []
        relations_context = []
    # RK3588_RELATION_CONTEXT_V1
    tokenizer = global_config.get("tokenizer")
'''


def install(path: Path) -> None:
    source = path.read_text()
    if MARKER in source:
        print(f"already installed: {path}")
        return
    function_start = source.find("async def _build_context_str(")
    if function_start < 0:
        raise SystemExit("unsupported LightRAG source; context builder not found")
    next_function = source.find("\nasync def ", function_start + 1)
    anchor_start = source.find(ANCHOR, function_start)
    if anchor_start < 0 or (
        next_function >= 0 and anchor_start >= next_function
    ):
        raise SystemExit(
            "unsupported LightRAG source; context tokenizer anchor not found"
        )
    backup = path.with_suffix(path.suffix + ".before-rk-relation-context")
    if not backup.exists():
        backup.write_text(source)
    path.write_text(
        source[:anchor_start] + INSERT + source[anchor_start + len(ANCHOR) :]
    )
    print(f"installed: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    install(args.path)


if __name__ == "__main__":
    main()
