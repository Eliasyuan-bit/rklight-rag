#!/usr/bin/env python3
"""Install the query-status banner as a small WebUI extension."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

MARKER = "<!-- RK3588_QUERY_STATUS_BANNER -->"
TAG = f'    {MARKER}\n    <script src="./query-status-banner.js"></script>\n'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("webui_dir", type=Path)
    parser.add_argument("banner_source", type=Path)
    args = parser.parse_args()
    index = args.webui_dir / "index.html"
    target = args.webui_dir / "query-status-banner.js"
    text = index.read_text()
    if MARKER not in text:
        if "  </body>" not in text:
            raise SystemExit("unsupported LightRAG WebUI index: missing </body>")
        backup = index.with_suffix(".html.before-rk3588-query-status-banner")
        if not backup.exists():
            backup.write_text(text)
        index.write_text(text.replace("  </body>", TAG + "  </body>", 1))
        print(f"patched: {index}")
    else:
        print(f"already patched: {index}")
    shutil.copyfile(args.banner_source, target)
    print(f"installed: {target}")


if __name__ == "__main__":
    main()
