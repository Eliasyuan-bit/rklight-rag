#!/usr/bin/env python3
"""Append structured LightRAG references to streamed answer text."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_REFERENCE_FOOTER_V1"
IMPORT_ANCHOR = "from lightrag.utils import logger\n"
IMPORT_INSERT = (
    IMPORT_ANCHOR
    + "from lightrag.rk_reference_markdown import render_reference_markdown\n"
    + MARKER
    + "\n"
)
STREAM_ANCHOR = '''                    except Exception as e:
                        logger.error(f"Streaming error: {str(e)}")
                        yield f"{json.dumps({'error': str(e)})}\\n"
'''
STREAM_INSERT = STREAM_ANCHOR + '''
                if include_references:
                    reference_footer = render_reference_markdown(references)
                    if reference_footer:
                        yield f"{json.dumps({'response': reference_footer})}\\n"
'''
NONSTREAM_ANCHOR = '''                complete_response = {"response": response_content}
'''
NONSTREAM_INSERT = '''                if include_references:
                    response_content += render_reference_markdown(references)
                complete_response = {"response": response_content}
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
    backup = path.with_suffix(path.suffix + ".before-rk3588-reference-footer")
    if not backup.exists():
        backup.write_text(source)
    source = replace_once(source, IMPORT_ANCHOR, IMPORT_INSERT, "logger import")
    source = replace_once(source, STREAM_ANCHOR, STREAM_INSERT, "stream handler")
    source = replace_once(source, NONSTREAM_ANCHOR, NONSTREAM_INSERT, "non-stream handler")
    path.write_text(source)
    print(f"installed: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    install(args.path)


if __name__ == "__main__":
    main()
