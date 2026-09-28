#!/usr/bin/env python3
"""Install the in-page evidence reader into LightRAG's existing WebUI."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


MARKER = "<!-- RK3588_REFERENCE_READER_V1 -->"
TAG = f'    {MARKER}\n    <script src="./reference-reader.js"></script>\n'


def install(webui_dir: Path, script: Path) -> None:
    index = webui_dir / "index.html"
    target = webui_dir / "reference-reader.js"
    source = index.read_text()
    if MARKER not in source:
        if "  </body>" not in source:
            raise SystemExit("unsupported LightRAG WebUI index: missing </body>")
        backup = index.with_suffix(".html.before-rk3588-reference-reader")
        if not backup.exists():
            backup.write_text(source)
        index.write_text(source.replace("  </body>", TAG + "  </body>", 1))
    shutil.copyfile(script, target)
    print(f"installed: {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("webui_dir", type=Path)
    parser.add_argument("script", type=Path)
    args = parser.parse_args()
    install(args.webui_dir, args.script)
