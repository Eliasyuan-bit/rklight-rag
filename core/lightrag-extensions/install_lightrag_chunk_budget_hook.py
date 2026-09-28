#!/usr/bin/env python3
"""Make LightRAG clip top evidence instead of returning zero source chunks."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_CHUNK_BUDGET_FALLBACK_V1"
IMPORT_ANCHOR = (
    "from lightrag.exceptions import ChunkBlockMatchError, EmptyTruncatedResponseError\n"
)
IMPORT_INSERT = IMPORT_ANCHOR + (
    "from lightrag.rk_chunk_budget import fit_first_evidence_chunk\n"
)
FALLBACK_ANCHOR = '''    k = len(approx)
    while k > 0:
'''
FALLBACK_INSERT = '''    if not approx and chunks:
        approx = fit_first_evidence_chunk(
            chunks,
            max_token_size,
            tokenizer,
            generate_reference_list_from_chunks,
            render_chunks_context_text,
        )
        if approx:
            logger.info(
                "Chunk token fallback: clipped top evidence chunk to %d chars for %d tokens",
                len(str(approx[0].get("content") or "")),
                max_token_size,
            )

    # RK3588_CHUNK_BUDGET_FALLBACK_V1
    k = len(approx)
    while k > 0:
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
    backup = path.with_suffix(path.suffix + ".before-rk3588-chunk-budget")
    if not backup.exists():
        backup.write_text(source)
    source = replace_once(source, IMPORT_ANCHOR, IMPORT_INSERT, "utils import")
    source = replace_once(source, FALLBACK_ANCHOR, FALLBACK_INSERT, "chunk fallback")
    path.write_text(source)
    print(f"installed: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    install(args.path)


if __name__ == "__main__":
    main()
