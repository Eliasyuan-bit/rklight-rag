"""Chunk-level reference metadata for traceable RAG answers."""
from __future__ import annotations

import re
from typing import Any


_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")


def _section_from_chunk(chunk: dict[str, Any]) -> str | None:
    headings = chunk.get("content_headings")
    if isinstance(headings, str) and headings.strip():
        return headings.strip()[:200]
    if isinstance(headings, list):
        path = " > ".join(str(item).strip() for item in headings if str(item).strip())
        if path:
            return path[:200]
    for line in str(chunk.get("content") or "").splitlines():
        match = _HEADING_RE.match(line)
        if match:
            return match.group(1).strip(" *_`").strip()[:200] or None
    return None


def _table_location_from_chunk(chunk: dict[str, Any]) -> str | None:
    """Describe a selected table row without fabricating a page or cell span."""
    if not chunk.get("table_parent"):
        return None
    title = str(chunk.get("table_title") or "").strip()
    records = chunk.get("table_row_records") or []
    labels: list[str] = []
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            fields = record.get("fields") or {}
            cells = record.get("cells") or []
            label = str(
                fields.get("Model Name")
                or (cells[0] if isinstance(cells, list) and cells else "")
                or record.get("raw")
                or ""
            ).strip()
            if label and label not in labels:
                labels.append(label[:160])
    parts = []
    if title:
        parts.append(f"表格：{title[:200]}")
    if labels:
        parts.append("行：" + "、".join(labels))
    return "；".join(parts) or None


def generate_chunk_reference_list(
    chunks: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Assign one stable reference ID to every surviving evidence chunk."""
    references: list[dict[str, str]] = []
    updated_chunks: list[dict[str, Any]] = []
    for chunk in chunks:
        updated = chunk.copy()
        file_path = str(updated.get("file_path") or "")
        chunk_id = str(
            updated.get("reference_chunk_id") or updated.get("chunk_id") or updated.get("id") or ""
        )
        if not file_path or file_path == "unknown_source":
            updated["reference_id"] = ""
            updated_chunks.append(updated)
            continue

        reference_id = str(len(references) + 1)
        updated["reference_id"] = reference_id
        reference = {
            "reference_id": reference_id,
            "file_path": file_path,
            "chunk_id": chunk_id,
        }
        section = _section_from_chunk(updated)
        if section:
            reference["section"] = section
        evidence_location = _table_location_from_chunk(updated)
        if evidence_location:
            reference["evidence_location"] = evidence_location
        references.append(reference)
        updated_chunks.append(updated)
    return references, updated_chunks


def enrich_reference_locations(
    references: list[dict[str, Any]], chunks: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """Restore a precise table location from final evidence plus the query.

    LightRAG's final context projection can discard sidecar table metadata.
    The API boundary still has the retained chunk text and original query, so
    this deterministic fallback reconstructs only a validated matching row.
    """
    try:
        # Runtime imports this module as ``lightrag.rk_chunk_citations``;
        # unit tests may load it as a standalone module.
        from .rk_table_parent import expand_table_parent
    except ImportError:
        try:
            from rk_table_parent import expand_table_parent
        except ImportError:
            return references
    chunks_by_ref: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        ref_id = str(chunk.get("reference_id") or "")
        if ref_id:
            chunks_by_ref.setdefault(ref_id, []).append(chunk)
    enriched = []
    for reference in references:
        item = reference.copy()
        if item.get("evidence_location"):
            enriched.append(item)
            continue
        for chunk in chunks_by_ref.get(str(item.get("reference_id") or ""), []):
            expanded = expand_table_parent(query, chunk)
            if not expanded or not expanded.get("table_evidence_valid"):
                continue
            location = _table_location_from_chunk(expanded)
            if location:
                item["evidence_location"] = location
                break
        enriched.append(item)
    return enriched
