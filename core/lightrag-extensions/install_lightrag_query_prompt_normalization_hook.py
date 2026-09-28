#!/usr/bin/env python3
"""Normalize blank QueryRequest.user_prompt values at the API boundary."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_QUERY_PROMPT_NORMALIZATION_V1"
ANCHOR = '''    @field_validator("query", mode="after")
'''
INSERT = '''    @field_validator("user_prompt", mode="before")
    @classmethod
    def normalize_blank_user_prompt(cls, value: object) -> object:
        # Browsers serialize an empty input as an explicit empty string, which
        # would otherwise override the field default. Normalize at the API
        # boundary so prompt rendering, cache identity and token accounting all
        # observe the same configured value.
        if value is None or (isinstance(value, str) and not value.strip()):
            return os.getenv("RK_DEFAULT_USER_PROMPT") or None
        return value

    # RK3588_QUERY_PROMPT_NORMALIZATION_V1
    @field_validator("query", mode="after")
'''


def install(path: Path) -> None:
    source = path.read_text()
    if MARKER in source:
        print(f"already installed: {path}")
        return
    if source.count(ANCHOR) != 1:
        raise SystemExit(
            f"unsupported query routes; expected one validator anchor, got {source.count(ANCHOR)}"
        )
    backup = path.with_suffix(path.suffix + ".before-rk-query-prompt-normalization")
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
