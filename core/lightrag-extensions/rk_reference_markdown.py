"""Render trusted structured references as a compact Markdown footer."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote


def display_source_name(file_path: str) -> str:
    """Hide ingestion-variant suffixes while retaining the document type."""
    name = Path(file_path).name
    for variant in (".kg.md", ".text.md"):
        if name.casefold().endswith(variant):
            return name[: -len(variant)] + ".md"
    return name


def reference_preview_url(chunk_id: str, other_hits: list[str] | None = None) -> str:
    path = "/query/references/" + quote(chunk_id, safe="") + "/view"
    if other_hits:
        path += "?hits=" + quote(",".join(other_hits), safe=",")
    return path + "#cited-passage"


def render_reference_markdown(references: list[dict[str, Any]]) -> str:
    """Return a deterministic footer without asking the LLM to cite sources."""
    lines: list[str] = []
    seen: set[str] = set()
    groups: dict[str, list[dict[str, Any]]] = {}
    for reference in references:
        reference_id = str(reference.get("reference_id") or "").strip()
        file_path = str(reference.get("file_path") or "").strip()
        if not reference_id or not file_path or reference_id in seen:
            continue
        seen.add(reference_id)
        # A missing upload identity must not cause two unrelated same-named
        # documents to be silently merged.
        key = str(reference.get("source_group_id") or reference_id)
        groups.setdefault(key, []).append(reference)
    for group in groups.values():
        first = group[0]
        label = f"[{first['reference_id']}] {display_source_name(str(first['file_path']))}"
        section = str(first.get("section") or "").strip()
        if len(group) > 1:
            label += f" · {len(group)} 处命中"
        elif section:
            label += f" — {section}"
        chunk_id = str(first.get("chunk_id") or "").strip()
        if chunk_id:
            other_hits = list(dict.fromkeys(
                str(item.get("chunk_id") or "").strip() for item in group[1:]
            ))
            other_hits = [hit for hit in other_hits if hit and hit != chunk_id]
            link_label = label.replace("[", r"\[").replace("]", r"\]")
            label = f"[{link_label}]({reference_preview_url(chunk_id, other_hits)})"
        lines.append(f"- {label}")
    if not lines:
        return ""
    return "\n\n### References\n\n" + "\n".join(lines)
