#!/usr/bin/env python3
"""Normalize an empty API user prompt to RK_DEFAULT_USER_PROMPT."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_USER_PROMPT_FALLBACK_V1"
ANCHOR = '    user_prompt = query_param.user_prompt if query_param.user_prompt else ""\n'
INSERT = '''    # Web clients commonly serialize an empty input as ``""``. Treat an
    # empty or whitespace-only value like an omitted field so browser and API
    # requests inherit the same configured answer contract.
    user_prompt = (
        query_param.user_prompt
        if query_param.user_prompt and query_param.user_prompt.strip()
        else os.getenv("RK_DEFAULT_USER_PROMPT", "")
    )
    # RK3588_USER_PROMPT_FALLBACK_V1
'''


def install(path: Path) -> None:
    source = path.read_text()
    if MARKER in source:
        print(f"already installed: {path}")
        return
    if source.count(ANCHOR) != 1:
        raise SystemExit(
            f"unsupported LightRAG source; expected one user prompt anchor, got {source.count(ANCHOR)}"
        )
    backup = path.with_suffix(path.suffix + ".before-rk-user-prompt-fallback")
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
