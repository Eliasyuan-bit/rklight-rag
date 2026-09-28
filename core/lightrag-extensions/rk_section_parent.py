"""Recover a complete Markdown section before neural reranking."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
from typing import Any

logger = logging.getLogger(__name__)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_ASCII_TERM_RE = re.compile(r"[a-z][a-z0-9_-]{1,}", re.IGNORECASE)
_IDENTIFIER_RE = re.compile(r"[a-z][a-z0-9]*(?:[._/:+-][a-z0-9]+)+", re.IGNORECASE)
_INDEX_CACHE: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}


def _enabled() -> bool:
    return os.getenv("RK_SECTION_PARENT_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def _query_terms(query: str) -> tuple[set[str], set[str]]:
    folded = query.casefold()
    ascii_terms = set(_ASCII_TERM_RE.findall(folded)) | set(_IDENTIFIER_RE.findall(folded))
    chinese = "".join(re.findall(r"[\u3400-\u9fff]", query))
    return ascii_terms, {chinese[index:index + 2] for index in range(len(chinese) - 1)}


def _clean_heading(value: str) -> str:
    return re.sub(r"[*`_]+", "", value).strip()


def extract_section_parents(content: str, fallback_heading: str = "") -> list[dict[str, Any]]:
    """Return Markdown sections, each ending at its next sibling/ancestor."""
    matches = list(_HEADING_RE.finditer(content))
    if not matches:
        body = content.strip()
        return ([{"heading": _clean_heading(fallback_heading), "level": 0, "content": body, "start": 0, "end": len(content)}] if body else [])
    sections = []
    for index, match in enumerate(matches):
        level = len(match.group(1))
        end = next((later.start() for later in matches[index + 1:] if len(later.group(1)) <= level), len(content))
        value = content[match.start():end].strip()
        if content[match.end():end].strip():
            sections.append({"heading": _clean_heading(match.group(2)), "level": level, "content": value, "start": match.start(), "end": end})
    return sections


def _section_score(section: dict[str, Any], ascii_terms: set[str], chinese_terms: set[str]) -> int:
    heading = str(section["heading"]).casefold()
    body = str(section["content"]).casefold()
    heading_hits = sum(term in heading for term in ascii_terms) + sum(term in heading for term in chinese_terms)
    body_hits = sum(term in body for term in ascii_terms) + sum(term in body for term in chinese_terms)
    # Heading coverage is a generic structural boundary signal. Body-only hits
    # need multiple terms before they are allowed to replace a candidate.
    return heading_hits * 8 + min(body_hits, 6)


def _load_records(global_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    working_dir = global_config.get("working_dir") or global_config.get("WORKING_DIR")
    path = Path(str(working_dir)) / "kv_store_text_chunks.json" if working_dir else None
    if path is None:
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    key = str(path)
    cached = _INDEX_CACHE.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Section parent store unavailable: %s", exc)
        return {}
    records = raw if isinstance(raw, dict) else {}
    _INDEX_CACHE[key] = (mtime, records)
    return records


def prioritize_section_parents(chunks: list[dict[str, Any]], query: str, global_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Replace one candidate with its best matching complete section.

    At most one section is emitted per source chunk so citations retain their
    original chunk ID. Tables are excluded because their dedicated parent
    evidence already guarantees title/header/row atomicity.
    """
    if not _enabled() or not query.strip() or not chunks:
        return chunks
    ascii_terms, chinese_terms = _query_terms(query)
    if not ascii_terms and not chinese_terms:
        return chunks
    records = _load_records(global_config)
    threshold = max(1, int(os.getenv("RK_SECTION_PARENT_MIN_SCORE", "8")))
    result, restored = [], 0
    for chunk in chunks:
        if chunk.get("table_parent"):
            result.append(chunk)
            continue
        source_id = str(chunk.get("source_chunk_id") or chunk.get("chunk_id") or chunk.get("id") or "")
        record = records.get(source_id, {})
        original = str(chunk.get("source_full_content") or chunk.get("full_content") or record.get("content") or chunk.get("content") or "")
        fallback = str(record.get("heading", {}).get("heading") or "") if isinstance(record.get("heading"), dict) else ""
        sections = extract_section_parents(original, fallback)
        if len(sections) < 2:
            result.append(chunk)
            continue
        score, section = max(((_section_score(value, ascii_terms, chinese_terms), value) for value in sections), key=lambda pair: (pair[0], pair[1]["level"], -pair[1]["start"]))
        if score < threshold:
            result.append(chunk)
            continue
        item = chunk.copy()
        item.update({
            "source_chunk_id": source_id,
            "source_full_content": original,
            "full_content": section["content"],
            "content": section["content"],
            "section_parent": True,
            "section_parent_heading": section["heading"],
            "section_parent_level": section["level"],
            "section_parent_score": score,
            "section_parent_range": [section["start"], section["end"]],
        })
        result.append(item)
        restored += 1
    if restored:
        logger.info("Section parent recovery: candidates=%d restored=%d", len(chunks), restored)
    return result
