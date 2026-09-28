#!/usr/bin/env python3
"""Keep WebUI pipeline status busy until single-card model restoration ends."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK_MODEL_TRANSITION_STATUS_V1"
IMPORT_ANCHOR = "import os\n"
IMPORT_INSERT = (
    IMPORT_ANCHOR
    + "from lightrag.rk_ingest_model_mode import model_transition_active\n"
    + MARKER
    + "\n"
)
DOCUMENT_ANCHOR = '''            # Sanitized fence projection BEFORE the internal fields are dropped
'''
DOCUMENT_INSERT = '''            # The core pipeline may release its ingestion slot before the
            # single-card gateway finishes restoring query workers. Keep the
            # presentation status active without changing pipeline admission.
            if model_transition_active():
                status_dict["busy"] = True

            # Sanitized fence projection BEFORE the internal fields are dropped
'''
HEALTH_ANCHOR = '''            pipeline_busy = bool(pipeline_snapshot.get("busy", False))
'''
HEALTH_INSERT = '''            pipeline_busy = bool(
                pipeline_snapshot.get("busy", False) or model_transition_active()
            )
'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(
            f"unsupported LightRAG source; expected one {label}, got {count}"
        )
    return source.replace(old, new, 1)


def install_document_routes(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return
    source = replace_once(source, IMPORT_ANCHOR, IMPORT_INSERT, "import anchor")
    source = replace_once(
        source, DOCUMENT_ANCHOR, DOCUMENT_INSERT, "pipeline status anchor"
    )
    path.write_text(source, encoding="utf-8")


def install_server(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return
    source = replace_once(source, IMPORT_ANCHOR, IMPORT_INSERT, "import anchor")
    source = replace_once(source, HEALTH_ANCHOR, HEALTH_INSERT, "health anchor")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("document_routes", type=Path)
    parser.add_argument("server", type=Path)
    args = parser.parse_args()
    install_document_routes(args.document_routes)
    install_server(args.server)


if __name__ == "__main__":
    main()
