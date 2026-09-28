"""Bounded, stateless pagination helpers for LightRAG graph extraction."""
from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


MORE_DELIMITER = "<|MORE|>"
COMPLETE_DELIMITER = "<|COMPLETE|>"


def split_extraction_windows(text: str, *, max_chars: int = 220) -> list[str]:
    """Split one stored chunk into sentence-aligned extraction-only windows."""
    if max_chars < 80:
        raise ValueError("max_chars must be at least 80")
    text = text.strip()
    if not text or len(text) <= max_chars:
        return [text]

    sentences = [
        part.strip()
        for part in re.findall(r"[^。！？；.!?\n]+(?:[。！？；.!?]+|\n+|$)", text)
        if part.strip()
    ]
    units: list[str] = []
    overlap = min(40, max_chars // 5)
    for sentence in sentences:
        if len(sentence) <= max_chars:
            units.append(sentence)
            continue
        start = 0
        while start < len(sentence):
            end = min(len(sentence), start + max_chars)
            units.append(sentence[start:end])
            if end == len(sentence):
                break
            start = end - overlap

    windows: list[str] = []
    current = ""
    for unit in units:
        candidate = unit if not current else f"{current}{unit}"
        if current and len(candidate) > max_chars:
            windows.append(current)
            current = unit
        else:
            current = candidate
    if current:
        windows.append(current)
    return windows or [text]


def extraction_needs_next_page(result: str, *, truncated: bool) -> bool:
    """Return whether extraction must continue on a fresh, stateless page."""
    if truncated:
        return True
    # A small local model may omit the terminal marker even after producing a
    # normal, complete response. Treating every missing marker as MORE causes
    # repeated audit calls and can exhaust the page budget. Continuation is
    # therefore opt-in: the model must explicitly emit MORE, or the gateway
    # must report a token-limit truncation.
    return MORE_DELIMITER in result


def _bounded_join(values: list[str], max_chars: int) -> str:
    rendered: list[str] = []
    used = 0
    for value in values:
        cost = len(value) + (2 if rendered else 0)
        if rendered and used + cost > max_chars:
            rendered.append("…")
            break
        rendered.append(value)
        used += cost
    return ", ".join(rendered) if rendered else "(none)"


def build_seen_summary(
    nodes: Mapping[str, Any], edges: Mapping[Any, Any], *, max_chars: int = 1600
) -> str:
    """Render only stable record identities, never prior generated descriptions."""
    entity_budget = max(200, max_chars // 2)
    relation_budget = max(200, max_chars - entity_budget)
    entity_names = sorted(str(name) for name in nodes)
    relation_names = sorted(
        f"{key[0]} -> {key[1]}"
        if isinstance(key, tuple) and len(key) >= 2
        else str(key)
        for key in edges
    )
    return (
        f"Entities: {_bounded_join(entity_names, entity_budget)}\n"
        f"Relations: {_bounded_join(relation_names, relation_budget)}"
    )


def build_continue_prompt(
    *,
    input_text: str,
    heading_context_block: str,
    seen_summary: str,
    page_no: int,
    max_pages: int,
    window_no: int,
    window_count: int,
    max_total_records: int,
    max_entity_records: int,
    language: str,
) -> str:
    """Build a fresh continuation request without replaying prior LLM output."""
    return f"""---Task---
Continue extracting entities and relationships from the same input text.

---Pagination---
- This is page {page_no} of at most {max_pages}.
- This page covers extraction window {window_no} of {window_count} from the stored chunk.
- Do not repeat anything listed under `---Already Extracted---`.
- Output at most {max_total_records} total rows and at most {max_entity_records} entity rows.
- Keep entity descriptions to one compact factual phrase of at most 16 words.
- Keep relation descriptions to one compact factual phrase of at most 20 words.
- Each entity row must contain exactly 4 fields; each relation row exactly 5 fields.
- Never put commas or tuple delimiters inside a field; use short phrases only.
- A relation may reference an entity listed under `---Already Extracted---`.
- If relevant unreported records remain, finish with the literal marker {MORE_DELIMITER}.
- Only when the input has been fully exhausted, finish with the literal marker {COMPLETE_DELIMITER}.
- Output only records followed by one marker. Use {language}.
- If the preceding response was cut off, emit its incomplete final record again in full.

---Already Extracted---
{seen_summary}

{heading_context_block}---Input Text---
```
{input_text}
```

---Output---
"""


def merge_extraction_page(
    target_nodes: dict[Any, list[dict[str, Any]]],
    target_edges: dict[Any, list[dict[str, Any]]],
    page_nodes: Mapping[Any, list[dict[str, Any]]],
    page_edges: Mapping[Any, list[dict[str, Any]]],
) -> int:
    """Merge a page and return the number of newly discovered record keys."""
    added = 0
    for entity_name, entities in page_nodes.items():
        if entity_name not in target_nodes:
            target_nodes[entity_name] = list(entities)
            added += 1
            continue
        current_len = len(target_nodes[entity_name][0].get("description", "") or "")
        candidate_len = len(entities[0].get("description", "") or "")
        if candidate_len > current_len:
            target_nodes[entity_name] = list(entities)

    for edge_key, edges in page_edges.items():
        if edge_key not in target_edges:
            target_edges[edge_key] = list(edges)
            added += 1
            continue
        current_len = len(target_edges[edge_key][0].get("description", "") or "")
        candidate_len = len(edges[0].get("description", "") or "")
        if candidate_len > current_len:
            target_edges[edge_key] = list(edges)
    return added
