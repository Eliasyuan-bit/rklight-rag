#!/usr/bin/env python3
"""Split the temporary Naive retrieval timing into vector and lexical steps."""

from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK_VECTOR_TIMING_PROBE_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operate_path", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = args.operate_path
    source = path.read_text()
    if MARKER in source:
        raise SystemExit("vector timing probe already installed")
    start = source.index("async def _get_vector_context(\n")
    end = source.index("async def _perform_kg_search(\n", start)
    section = source[start:end]
    section = replace_once(
        section,
        "    if not results:\n",
        '    _rk_timing_mark("vector_query_done")  # RK_VECTOR_TIMING_PROBE_V1\n'
        "    if not results:\n",
        "vector query",
    )
    section = replace_once(
        section,
        '    logger.info(\n        f"Naive query: {len(valid_chunks)} candidate chunks "\n',
        '    _rk_timing_mark("lexical_fusion_done")\n'
        '    logger.info(\n        f"Naive query: {len(valid_chunks)} candidate chunks "\n',
        "lexical fusion",
    )
    modified = source[:start] + section + source[end:]
    compile(modified, str(path), "exec")
    if args.check:
        print(f"vector timing probe anchors and syntax OK: {path}")
        return
    backup = path.with_suffix(path.suffix + ".before-rk-vector-timing-probe")
    if backup.exists():
        raise SystemExit(f"backup already exists: {backup}")
    backup.write_text(source)
    path.write_text(modified)
    print(f"installed vector timing probe: {path}; backup: {backup}")


if __name__ == "__main__":
    main()
