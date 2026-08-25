#!/usr/bin/env python3
"""Add selective-route grouping to LightRAG's document list and delete API."""
from __future__ import annotations

import argparse
from pathlib import Path

MARKER = "# RK3588_SELECTIVE_DOCUMENT_GROUPING_HOOK\n"
IMPORT_ANCHOR = "ARCHIVED_FILE_SUFFIX_RE = re.compile(r\"_(?:\\d{3}|\\d{10,})$\")\n"
IMPORT_INSERT = '''ARCHIVED_FILE_SUFFIX_RE = re.compile(r"_(?:\\d{3}|\\d{10,})$")
# RK3588_SELECTIVE_DOCUMENT_GROUPING_HOOK
SELECTIVE_SOURCE_RE = re.compile(r"<!--\\s*source:\\s*(.+?);\\s*route:\\s*(?:kg|text-only)\\s*-->", re.I)

def selective_source(doc):
    summary = doc.get("content_summary", "") if isinstance(doc, dict) else getattr(doc, "content_summary", "")
    metadata = doc.get("metadata", {}) if isinstance(doc, dict) else (getattr(doc, "metadata", {}) or {})
    if str((metadata or {}).get("process_options", "")) not in {"P", "P!"}:
        return None
    match = SELECTIVE_SOURCE_RE.search(str(summary or ""))
    return match.group(1).strip() if match else None
'''
DELETE_ANCHOR = "        doc_ids = delete_request.doc_ids\n"
DELETE_INSERT = '''        doc_ids = delete_request.doc_ids
        # Selecting the user-visible KG row must also delete its P! sibling.
        expanded_doc_ids = list(doc_ids)
        selected_docs = await rag.aget_docs_by_ids(doc_ids)
        for _, selected in selected_docs.items():
            source = selective_source(selected)
            track_id = selected.get("track_id") if isinstance(selected, dict) else getattr(selected, "track_id", None)
            if not source or not track_id:
                continue
            for sibling_id, sibling in (await rag.aget_docs_by_track_id(track_id)).items():
                if selective_source(sibling) == source and sibling_id not in expanded_doc_ids:
                    expanded_doc_ids.append(sibling_id)
        doc_ids = expanded_doc_ids
'''
LIST_ANCHOR = "            # Calculate pagination info\n            total_pages = (total_count + request.page_size - 1) // request.page_size\n"
LIST_INSERT = '''            # Collapse P/P! siblings into their one user-visible source.
            grouped = {}
            passthrough = []
            for item in doc_responses:
                source = selective_source(item)
                if not source:
                    passthrough.append(item)
                    continue
                group = grouped.setdefault(source, [])
                group.append(item)
            for source, members in grouped.items():
                primary = next((item for item in members if str((item.metadata or {}).get("process_options")) == "P"), members[0])
                rank = {"failed": 4, "processing": 3, "pending": 2, "processed": 1}
                status_member = max(members, key=lambda item: rank.get(str(item.status).lower().split(".")[-1], 0))
                metadata = dict(primary.metadata or {})
                metadata["selective_route"] = {"source": source, "internal_doc_ids": [item.id for item in members], "parts": len(members)}
                passthrough.append(DocStatusResponse(
                    id=primary.id, content_summary=primary.content_summary,
                    content_length=sum(item.content_length for item in members), status=status_member.status,
                    created_at=min(item.created_at for item in members), updated_at=max(item.updated_at for item in members),
                    track_id=primary.track_id, chunks_count=sum(item.chunks_count or 0 for item in members),
                    error_msg=status_member.error_msg, metadata=metadata, file_path=source,
                ))
            doc_responses = passthrough
            total_count = len(doc_responses)
            status_counts = {}
            for item in doc_responses:
                key = str(item.status).lower().split(".")[-1]
                status_counts[key] = status_counts.get(key, 0) + 1

            # Calculate pagination info
            total_pages = (total_count + request.page_size - 1) // request.page_size
'''

def main():
    path = Path(argparse.ArgumentParser().parse_args().document_routes)

def install(path: Path):
    source = path.read_text()
    if MARKER in source:
        print(f"already installed: {path}")
        return
    for anchor in (IMPORT_ANCHOR, DELETE_ANCHOR, LIST_ANCHOR):
        if anchor not in source:
            raise SystemExit(f"unsupported LightRAG source; anchor missing: {anchor[:40]}")
    backup = path.with_suffix(path.suffix + ".before-selective-document-grouping")
    if not backup.exists(): backup.write_text(source)
    source = source.replace(IMPORT_ANCHOR, IMPORT_INSERT, 1)
    source = source.replace(DELETE_ANCHOR, DELETE_INSERT, 1)
    source = source.replace(LIST_ANCHOR, LIST_INSERT, 1)
    path.write_text(source)
    print(f"installed: {path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("document_routes", type=Path)
    install(parser.parse_args().document_routes)
