#!/usr/bin/env python3
"""Make the engineered document retrieval path the LightRAG API default."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_DEFAULT_QUERY_MODE_V1"
ANCHOR = '''    mode: Literal["local", "global", "hybrid", "naive", "mix", "bypass"] = Field(
        default="mix",
        description="Query mode",
    )
'''
INSERT = '''    mode: Literal["local", "global", "hybrid", "naive", "mix", "bypass"] = Field(
        default=os.getenv("RK_DEFAULT_QUERY_MODE", "mix"),
        description="Query mode",
    )
    # RK3588_DEFAULT_QUERY_MODE_V1
'''


def install(path: Path) -> None:
    source = path.read_text()
    if MARKER in source:
        print(f"already installed: {path}")
        return
    if source.count(ANCHOR) != 1:
        raise SystemExit(
            f"unsupported LightRAG source; expected one query mode anchor, got {source.count(ANCHOR)}"
        )
    backup = path.with_suffix(path.suffix + ".before-rk3588-query-default")
    if not backup.exists():
        backup.write_text(source)
    path.write_text(source.replace(ANCHOR, INSERT, 1))
    print(f"installed: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    install(args.path)


if __name__ == "__main__":
    main()
