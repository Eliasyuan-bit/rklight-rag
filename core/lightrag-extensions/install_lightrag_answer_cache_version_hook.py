#!/usr/bin/env python3
"""Make the answer-cache policy version configurable for retrieval changes."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_ANSWER_CACHE_VERSION_V1"
IMPORT_ANCHOR = "import logging\n"
IMPORT_INSERT = "import logging\nimport os\n"
VERSION_ANCHOR = '_ANSWER_CACHE_POLICY_VERSION = "query-answer-cache-v2"\n'
VERSION_INSERT = '''# RK3588_ANSWER_CACHE_VERSION_V1
_ANSWER_CACHE_POLICY_VERSION = os.getenv(
    "RK_ANSWER_CACHE_VERSION", "query-answer-cache-v2"
)
'''


def install(path: Path) -> None:
    source = path.read_text()
    if MARKER in source:
        print(f"already installed: {path}")
        return
    if source.count(IMPORT_ANCHOR) != 1 or source.count(VERSION_ANCHOR) != 1:
        raise SystemExit("unsupported LightRAG operate.py cache-version anchors")
    backup = path.with_suffix(path.suffix + ".before-rk3588-answer-cache-version")
    if not backup.exists():
        backup.write_text(source)
    source = source.replace(IMPORT_ANCHOR, IMPORT_INSERT, 1)
    source = source.replace(VERSION_ANCHOR, VERSION_INSERT, 1)
    path.write_text(source)
    print(f"installed: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    install(args.path)


if __name__ == "__main__":
    main()
