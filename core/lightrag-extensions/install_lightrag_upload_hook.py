#!/usr/bin/env python3
"""Install the selective Markdown upload hook into a LightRAG installation.

The hook is deliberately tiny: it only changes the ``/documents/upload``
handling of *plain* Markdown.  LightRAG still owns parsing, queueing,
embedding, graph extraction and retrieval.  PDF and explicitly hinted files
continue through the stock upload path unchanged.
"""

from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_SELECTIVE_MARKDOWN_UPLOAD_HOOK\n"
INDEX_MARKER = "# RK3588_SELECTIVE_MARKDOWN_UPLOAD_INDEX_LOOP\n"
ANCHOR = "            track_id = generate_track_id(\"upload\")\n"
INDEX_ANCHOR = '''                    await pipeline_index_file(
                        rag,
                        file_path,
                        track_id,
                        admission_token=enqueue_token,
                    )
'''
REPLACEMENT = '''            # RK3588_SELECTIVE_MARKDOWN_UPLOAD_HOOK
            # Plain Markdown is split into LightRAG-native P/P! sources before
            # enqueueing.  Explicit parser hints remain an expert override.
            index_paths = [file_path]
            if safe_filename.lower().endswith(".md") and ".[" not in safe_filename:
                from selective_ingest_router import route_markdown_file

                # Keep audit manifests outside INPUT_DIR: the latter is owned
                # by LightRAG's scanner and must contain indexable sources
                # only.
                route_dir = doc_manager.input_dir.parent / "route_manifests" / uuid4().hex
                try:
                    index_paths, manifest_path, route_manifest = route_markdown_file(
                        file_path, route_dir
                    )
                    if not index_paths:
                        raise ValueError("Markdown has no indexable blocks after routing")
                    routed_input_paths = []
                    for routed_path in index_paths:
                        target = doc_manager.input_dir / routed_path.name
                        if target.exists():
                            raise FileExistsError(f"Routed upload already exists: {target.name}")
                        shutil.move(str(routed_path), str(target))
                        routed_input_paths.append(target)
                    index_paths = routed_input_paths
                    file_path.unlink()
                    logger.info(
                        "[selective-ingest] %s -> %s (kg=%s, text_only=%s)",
                        safe_filename,
                        [path.name for path in index_paths],
                        route_manifest["block_counts"]["kg"],
                        route_manifest["block_counts"]["text_only"],
                    )
                except Exception:
                    # Do not leave a half-routed source in INPUT_DIR.  The
                    # outer error handling returns the failure to the caller.
                    for routed_path in index_paths:
                        if routed_path != file_path:
                            routed_path.unlink(missing_ok=True)
                    raise

            track_id = generate_track_id("upload")
'''
INDEX_REPLACEMENT = '''                    # RK3588_SELECTIVE_MARKDOWN_UPLOAD_INDEX_LOOP
                    # A routed Markdown upload has two independent LightRAG
                    # sources.  Use one track id so the UI can follow the
                    # upload as a single user operation.
                    for path_index, index_path in enumerate(index_paths):
                        await pipeline_index_file(
                            rag,
                            index_path,
                            track_id,
                            admission_token=enqueue_token if path_index == 0 else None,
                        )
'''


def install(target: Path) -> None:
    source = target.read_text(encoding="utf-8")
    has_route_hook = MARKER in source
    has_index_hook = INDEX_MARKER in source
    if has_route_hook and has_index_hook:
        print(f"already installed: {target}")
        return
    if not has_route_hook and ANCHOR not in source:
        raise SystemExit(f"unsupported LightRAG source: upload anchor not found in {target}")
    if not has_index_hook and INDEX_ANCHOR not in source:
        raise SystemExit(f"unsupported LightRAG source: upload index anchor not found in {target}")
    backup = target.with_suffix(target.suffix + ".before-selective-upload-hook")
    if not backup.exists():
        backup.write_text(source, encoding="utf-8")
    if not has_route_hook:
        source = source.replace(ANCHOR, REPLACEMENT, 1)
    if not has_index_hook:
        source = source.replace(INDEX_ANCHOR, INDEX_REPLACEMENT, 1)
    target.write_text(source, encoding="utf-8")
    print(f"installed: {target}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("document_routes", type=Path)
    args = parser.parse_args()
    install(args.document_routes)


if __name__ == "__main__":
    main()
