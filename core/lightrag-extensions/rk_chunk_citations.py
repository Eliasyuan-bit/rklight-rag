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


def generate_chunk_reference_list(
    chunks: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Assign one stable reference ID to every surviving evidence chunk."""
    references: list[dict[str, str]] = []
    updated_chunks: list[dict[str, Any]] = []
    for chunk in chunks:
        updated = chunk.copy()
        file_path = str(updated.get("file_path") or "")
        chunk_id = str(updated.get("chunk_id") or updated.get("id") or "")
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
        references.append(reference)
        updated_chunks.append(updated)
    return references, updated_chunks
