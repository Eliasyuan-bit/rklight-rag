#!/usr/bin/env python3
"""Install the safe chunk-preview endpoint into LightRAG query routes."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_REFERENCE_PREVIEW_V2"
OLD_MARKER = "# RK3588_REFERENCE_PREVIEW_V1"
IMPORT_ANCHOR = "from lightrag.rk_reference_markdown import render_reference_markdown\n"
IMPORT_INSERT = (
    IMPORT_ANCHOR
    + "from lightrag.rk_reference_preview import (\n"
    + "    build_reference_preview, render_reference_document, valid_chunk_id,\n"
    + ")\n"
    + MARKER
    + "\n"
)
ROUTE_ANCHOR = '''    @router.get("/query/status", dependencies=[Depends(combined_auth)])
    async def query_status(http_request: Request):
        """Return only aggregate queue state plus this browser's token state."""
        return await query_coordinator.snapshot(http_request.headers.get("x-rk-queue-token"))
'''
ROUTE_INSERT = ROUTE_ANCHOR + '''
    @router.get("/query/references/{chunk_id}", dependencies=[Depends(combined_auth)])
    async def query_reference_preview(chunk_id: str):
        """Return one bounded evidence chunk for the WebUI preview dialog."""
        if not valid_chunk_id(chunk_id):
            raise HTTPException(status_code=400, detail="Invalid chunk_id")
        chunk = await rag.text_chunks.get_by_id(chunk_id)
        if not isinstance(chunk, dict):
            raise HTTPException(status_code=404, detail="Reference chunk not found")
        return build_reference_preview(chunk_id, chunk)

    @router.get("/query/references/{chunk_id}/view", dependencies=[Depends(combined_auth)])
    async def query_reference_document(chunk_id: str):
        """Open the complete ingested Markdown and highlight its cited passage."""
        if not valid_chunk_id(chunk_id):
            raise HTTPException(status_code=400, detail="Invalid chunk_id")
        chunk = await rag.text_chunks.get_by_id(chunk_id)
        if not isinstance(chunk, dict):
            raise HTTPException(status_code=404, detail="Reference chunk not found")
        full_doc_id = str(chunk.get("full_doc_id") or "")
        full_doc = await rag.full_docs.get_by_id(full_doc_id) if full_doc_id else None
        from fastapi.responses import HTMLResponse
        return HTMLResponse(
            content=render_reference_document(chunk_id, chunk, full_doc),
        )
'''

OLD_IMPORT = (
    "from lightrag.rk_reference_markdown import render_reference_markdown\n"
    "from lightrag.rk_reference_preview import build_reference_preview, valid_chunk_id\n"
    + OLD_MARKER
    + "\n"
)
OLD_ROUTE = '''    @router.get("/query/references/{chunk_id}", dependencies=[Depends(combined_auth)])
    async def query_reference_preview(chunk_id: str):
        """Return one bounded evidence chunk for the WebUI preview dialog."""
        if not valid_chunk_id(chunk_id):
            raise HTTPException(status_code=400, detail="Invalid chunk_id")
        chunk = await rag.text_chunks.get_by_id(chunk_id)
        if not isinstance(chunk, dict):
            raise HTTPException(status_code=404, detail="Reference chunk not found")
        return build_reference_preview(chunk_id, chunk)
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
    backup = path.with_suffix(path.suffix + ".before-rk3588-reference-preview")
    if not backup.exists():
        backup.write_text(source)
    if OLD_MARKER in source:
        source = replace_once(source, OLD_IMPORT, IMPORT_INSERT, "v1 reference import")
        source = replace_once(source, OLD_ROUTE, ROUTE_INSERT[len(ROUTE_ANCHOR):], "v1 reference route")
    else:
        source = replace_once(source, IMPORT_ANCHOR, IMPORT_INSERT, "reference import")
        source = replace_once(source, ROUTE_ANCHOR, ROUTE_INSERT, "query status route")
    path.write_text(source)
    print(f"installed: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    install(args.path)


if __name__ == "__main__":
    main()
