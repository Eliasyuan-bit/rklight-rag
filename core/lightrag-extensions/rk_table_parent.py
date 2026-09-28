"""Structure-aware parent evidence for tables extracted from PDF/Markdown.

The retriever may recall a row, but the answer model needs the table schema that
gives that row meaning.  This module keeps table parsing independent from the
reranker: child rows are searchable, while a matching row can expand to its
parent (title, header and rows) before generation.
"""
from __future__ import annotations

import re
from typing import Any


_LLM_FIELDS = ("inputtokens", "newtokens", "ttft", "tpot", "decodetps")
_VLM_FIELDS = ("vision", "visual", "image", "fullmodal", "audio")
_ACCURACY_FIELDS = ("accuracy", "float32", "w4a16", "dataset")
_CONFIG_FIELDS = ("recommendedserver", "serverconfig", "estimatedconversion", "ssd")
_MODEL_RE = re.compile(r"\b(?:qwen|gemma|lfm|glm)[a-z0-9._-]*\b", re.I)
_PIPE_RE = re.compile(r"^\s*\|.*\|\s*$")
_SERVER_CONFIG_RE = re.compile(
    r"^(?P<model>.+?)\s+(?P<cpu>\d+-core\s+CPU)\s*/\s*"
    r"(?P<ram>\d+\s*GB\s+RAM)\s*/\s*"
    r"(?P<ssd>\d+\s*TB\s+SSD/HDD)\s+"
    r"(?P<time>~?\d+\s+minutes)$"
)

_LLM_PERF_COLUMNS = [
    "Model Name",
    "Accelerator",
    "Input Tokens",
    "New Tokens",
    "TTFT (ms)",
    "TPOT (ms)",
    "Decode TPS",
]
_LLM_ACCURACY_COLUMNS = [
    "Model Name",
    "Accelerator",
    "Dataset",
    "Acc (float32)",
    "Acc (RKNN3 W4A16 G32)",
]
_VLM_ACCURACY_COLUMNS = [
    "Model Name",
    "Dataset",
    "Acc (float32)",
    "Acc (RKNN3 W4A16 G32)",
]
_SERVER_CONFIG_COLUMNS = [
    "Model Name",
    "CPU",
    "RAM",
    "SSD",
    "Estimated Time",
]


class TableParent:
    def __init__(self, table_id: str, title: str, headers: list[str], rows: list[str],
                 table_type: str, source_chunk_id: str = "", source_file: str = "",
                 row_records: list[dict[str, Any]] | None = None,
                 source_chunk_order: int | None = None):
        self.table_id = table_id
        self.title = title
        self.headers = headers
        self.rows = rows
        self.table_type = table_type
        self.source_chunk_id = source_chunk_id
        self.source_file = source_file
        self.row_records = row_records or []
        self.source_chunk_order = source_chunk_order

    def render(self) -> str:
        parts = [self.title.strip()] if self.title.strip() else []
        columns = _schema_for(self.table_type, self.rows)
        if columns:
            # Docling's plain-text PDF export often flattens this header into
            # one token stream.  Preserve the source values, but restore the
            # public schema so the answer model cannot shift columns around.
            parts.extend((
                "| " + " | ".join(columns) + " |",
                "| " + " | ".join("---" for _ in columns) + " |",
            ))
            for row in self.rows:
                cells, row_columns = _parse_cells(row, self.table_type)
                if row_columns == columns and len(cells) == len(columns):
                    parts.append("| " + " | ".join(cells) + " |")
                else:
                    parts.append(row.strip())
            return "\n".join(parts).strip()
        if self.headers:
            parts.append(" | ".join(self.headers))
        parts.extend(row.strip() for row in self.rows if row.strip())
        return "\n".join(parts).strip()

    def as_record(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "title": self.title,
            "headers": self.headers,
            "rows": self.rows,
            "table_type": self.table_type,
            "source_chunk_id": self.source_chunk_id,
            "source_file": self.source_file,
            "row_records": self.row_records,
            "source_chunk_order": self.source_chunk_order,
        }


def _canonical_model(value: str) -> str:
    """Normalize a model identifier for matching only; preserve display text."""
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _model_keys(text: str) -> list[str]:
    return [_canonical_model(match.group(0)) for match in _MODEL_RE.finditer(text)]


def _split_row(raw: str) -> list[str]:
    """Split a typed row that may be pipe-formatted or whitespace-flattened."""
    raw = raw.strip()
    if raw.startswith("|") and raw.endswith("|"):
        return [part.strip() for part in raw.strip("|").split("|")]
    return raw.split()


def _parse_cells(raw: str, table_type: str) -> tuple[list[str], list[str] | None]:
    """Split one typed table row into cells aligned to its known schema.

    Flat PDF tables lose their column separators.  The known schemas are
    unambiguous enough to restore by whitespace or a dedicated pattern.  When
    a row does not match, it is returned as a single unparsed cell so callers
    keep the original text instead of inventing a field mapping.
    """
    raw = raw.strip()
    if table_type == "llm_performance":
        cells = _split_row(raw)
        return (cells, _LLM_PERF_COLUMNS) if len(cells) == len(_LLM_PERF_COLUMNS) else ([raw], None)
    if table_type == "accuracy":
        cells = _split_row(raw)
        if len(cells) == len(_LLM_ACCURACY_COLUMNS):
            return cells, _LLM_ACCURACY_COLUMNS
        if len(cells) == len(_VLM_ACCURACY_COLUMNS):
            return cells, _VLM_ACCURACY_COLUMNS
        return [raw], None
    if table_type == "server_config":
        cells = _split_row(raw)
        if len(cells) == len(_SERVER_CONFIG_COLUMNS):
            return cells, _SERVER_CONFIG_COLUMNS
        match = _SERVER_CONFIG_RE.match(raw)
        if match:
            return (
                [match.group("model").strip(), match.group("cpu"),
                 match.group("ram"), match.group("ssd"), match.group("time")],
                _SERVER_CONFIG_COLUMNS,
            )
        return [raw], None
    return [raw], None


def _schema_for(table_type: str, rows: list[str]) -> list[str] | None:
    """Return the fixed columns for a typed table, or ``None`` for generic tables."""
    if table_type == "llm_performance":
        return _LLM_PERF_COLUMNS
    if table_type == "server_config":
        return _SERVER_CONFIG_COLUMNS
    if table_type == "accuracy":
        for row in rows:
            cells = _split_row(row)
            if len(cells) == len(_LLM_ACCURACY_COLUMNS):
                return _LLM_ACCURACY_COLUMNS
            if len(cells) == len(_VLM_ACCURACY_COLUMNS):
                return _VLM_ACCURACY_COLUMNS
    return None


def _row_records(headers: list[str], rows: list[str], table_type: str) -> list[dict[str, Any]]:
    """Attach cells to their header in one row-level evidence object.

    Flattened PDF tables do not always expose separators.  Typed tables use
    their restored schemas; generic pipe tables use the detected header width.
    Unknown rows remain searchable but are not presented as validated metric
    records.
    """
    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        raw = row.strip()
        if not raw:
            continue
        if table_type in ("llm_performance", "accuracy", "server_config"):
            cells, schema = _parse_cells(raw, table_type)
        else:
            cells = [part.strip() for part in raw.strip("|").split("|")]
            schema = headers if len(cells) == len(headers) else None
        values = dict(zip(schema, cells)) if schema and len(cells) == len(schema) else {}
        records.append({
            "row_index": index,
            "raw": raw,
            "cells": cells,
            "fields": values,
            "model_key": _canonical_model(cells[0]) if cells else "",
            "validated": bool(values) and bool(_model_keys(cells[0] if cells else "")),
        })
    return records


def _select_rows(query: str, table: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    records = table.get("row_records") or _row_records(
        list(table.get("headers") or []), list(table.get("rows") or []), str(table.get("table_type") or "")
    )
    keys = _model_keys(query)
    if not keys:
        return list(table.get("rows") or []), records
    selected = [record for record in records if any(
        key == record.get("model_key") or key in str(record.get("model_key") or "")
        for key in keys
    )]
    if not selected:
        return list(table.get("rows") or []), records
    return [record["raw"] for record in selected], selected


def _render_record_fields(record: dict[str, Any]) -> str:
    """Render one validated row as ``field = value`` lines for the answer model."""
    fields = record.get("fields") or {}
    if not fields:
        return str(record.get("raw") or "")
    return "\n".join(
        f"- {key} = {value}" for key, value in fields.items() if value != ""
    )


def classify_table_type(title: str, headers: list[str], body: str) -> str:
    header_text = " ".join(str(header) for header in headers)
    # The restored/rendered schemas are unambiguous.  Prefer them so a table
    # parent can be re-parsed from its rendered markdown without losing its
    # type on the index -> retrieval -> expansion round trip.
    if "Acc (float32)" in header_text and "W4A16 G32" in header_text:
        return "accuracy"
    if (
        "Input Tokens" in header_text
        and "TTFT (ms)" in header_text
        and "Decode TPS" in header_text
    ):
        return "llm_performance"
    if all(column in header_text for column in _SERVER_CONFIG_COLUMNS):
        return "server_config"
    schema = re.sub(r"[^a-z0-9]+", "", " ".join((title, " ".join(headers))).casefold())
    compact = re.sub(r"[^a-z0-9]+", "", " ".join((title, " ".join(headers), body)).casefold())
    if sum(schema.count(field) for field in _ACCURACY_FIELDS) >= 2:
        return "accuracy"
    if sum(schema.count(field) for field in _CONFIG_FIELDS) >= 2:
        return "server_config"
    llm_hits = sum(compact.count(field) for field in _LLM_FIELDS)
    vlm_hits = sum(compact.count(field) for field in _VLM_FIELDS)
    if llm_hits >= 3 and vlm_hits < 2:
        return "llm_performance"
    if vlm_hits >= 2:
        return "vlm_performance"
    if llm_hits >= 3:
        return "llm_performance"
    return "unknown"


def _title_before(lines: list[str], start: int) -> str:
    for index in range(start - 1, max(-1, start - 4), -1):
        value = lines[index].strip()
        if value and not _PIPE_RE.match(value) and not re.match(r"^[-| :]+$", value):
            return re.sub(r"^#{1,6}\s+", "", value)
    return ""


def _pipe_tables(content: str) -> list[tuple[str, list[str], list[str]]]:
    lines = content.splitlines()
    tables: list[tuple[str, list[str], list[str]]] = []
    index = 0
    while index < len(lines):
        if not _PIPE_RE.match(lines[index]):
            index += 1
            continue
        start = index
        block: list[str] = []
        while index < len(lines) and _PIPE_RE.match(lines[index]):
            block.append(lines[index].strip())
            index += 1
        if len(block) < 2:
            continue
        cells = lambda value: [part.strip() for part in value.strip("|").split("|")]
        header = cells(block[0])
        body = [line for line in block[2:] if not re.match(r"^\s*\|?\s*:?-{2,}", line)]
        tables.append((_title_before(lines, start), header, body))
    return tables


def _flat_tables(content: str) -> list[tuple[str, list[str], list[str]]]:
    """Detect flattened Docling/PDF table blocks using schema and model rows."""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    tables: list[tuple[str, list[str], list[str]]] = []
    for index, line in enumerate(lines):
        compact = re.sub(r"[^a-z0-9]+", "", line.casefold())
        llm_hits = sum(compact.count(field) for field in _LLM_FIELDS)
        vlm_hits = sum(compact.count(field) for field in _VLM_FIELDS)
        accuracy_hits = sum(compact.count(field) for field in _ACCURACY_FIELDS)
        config_hits = sum(compact.count(field) for field in _CONFIG_FIELDS)
        if llm_hits < 3 and vlm_hits < 2 and accuracy_hits < 2 and config_hits < 2:
            continue
        rows: list[str] = []
        for candidate in lines[index + 1 :]:
            if _MODEL_RE.search(candidate):
                rows.append(candidate)
            elif rows and any(
                marker in candidate.casefold()
                for marker in (
                    "performance", "model accuracy", "recommended server",
                    "cnn model", "vlm model", "full-modal",
                )
            ):
                break
        if rows:
            title = next((value for value in reversed(lines[max(0, index - 3) : index]) if "performance" in value.casefold()), "LLM Model Performance")
            tables.append((title, [line], rows))
    return tables


def extract_table_parents(
    content: str, *, chunk_id: str = "", source_file: str = ""
) -> list[dict[str, Any]]:
    """Extract parent tables and annotate their searchable child rows."""
    candidates = _pipe_tables(content) or _flat_tables(content)
    parents: list[dict[str, Any]] = []
    for index, (title, headers, rows) in enumerate(candidates):
        table = TableParent(
            table_id=f"{chunk_id or 'chunk'}-table-{index:02d}",
            title=title,
            headers=headers,
            rows=rows,
            table_type=classify_table_type(title, headers, "\n".join(rows)),
            source_chunk_id=chunk_id,
            source_file=source_file,
        )
        table.row_records = _row_records(table.headers, table.rows, table.table_type)
        parents.append(table.as_record())
    return parents


def table_query_type(query: str) -> str | None:
    folded = query.casefold()
    if any(term in folded for term in ("服务器", "server", "转换时间", "conversion time", "内存", "ssd")):
        return "server_config"
    if any(term in folded for term in ("精度", "accuracy", "float32", "w4a16")):
        return "accuracy"
    if any(term in folded for term in ("视觉", "vlm", "vision", "full-modal", "图像")):
        return "vlm_performance"
    if any(term in folded for term in ("性能", "ttft", "tpot", "decode", "吞吐")):
        return "llm_performance"
    return None


def prioritize_typed_table_parents(
    chunks: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """Reserve schema-matched table parents before neural reranking.

    A reranker scores a table parent as a long passage and can prefer an
    unrelated short row with the same model name.  For a query that explicitly
    asks for a known table schema (LLM performance, VLM performance, accuracy,
    or server configuration), the typed parent is the primary evidence unit.
    This function is deliberately called *before* reranking, while sidecar
    metadata is still present.
    """
    expected = table_query_type(query)
    if expected is None:
        return chunks
    matched: list[dict[str, Any]] = []
    for item in chunks:
        table_type = str(item.get("table_type") or "")
        is_parent = bool(item.get("table_parent"))
        # Some LightRAG merge paths retain only chunk_id/content, discarding
        # sidecar fields.  The synthetic table id is stable and content still
        # contains the rendered table schema, so restore the classification
        # here before handing candidates to the reranker.
        if not is_parent and "-table-" in str(item.get("chunk_id") or item.get("id") or ""):
            content = str(item.get("full_content") or item.get("content") or "")
            extracted = extract_table_parents(content)
            if extracted:
                table_type = str(extracted[0].get("table_type") or "")
                is_parent = True
        if is_parent and table_type == expected:
            restored = item.copy()
            restored["table_parent"] = True
            restored["table_type"] = table_type
            # Keep row-level fields available to downstream validation even
            # when LightRAG dropped the sidecar metadata during merge.
            if not restored.get("row_records"):
                extracted = extract_table_parents(
                    str(restored.get("full_content") or restored.get("content") or "")
                )
                if extracted:
                    restored["row_records"] = extracted[0].get("row_records", [])
            matched.append(restored)
    return matched or chunks


def expand_table_parent(query: str, chunk: dict[str, Any]) -> dict[str, Any] | None:
    """Return a typed parent bundle when the chunk contains a matching table."""
    expected = table_query_type(query)
    if expected is None:
        return None
    content = str(chunk.get("full_content") or chunk.get("content") or "")
    tables = extract_table_parents(
        content,
        chunk_id=str(chunk.get("chunk_id") or chunk.get("id") or ""),
        source_file=str(chunk.get("file_path") or ""),
    )
    matching = [table for table in tables if table["table_type"] == expected]
    if not matching:
        return None
    # The parent remains atomic; downstream evidence compaction must not split
    # its title/header/rows into unrelated prose units.
    selected = matching[0]
    selected_rows, selected_records = _select_rows(query, selected)
    result = chunk.copy()
    # A model-specific query should transcribe one labelled row instead of
    # re-aligning a flattened multi-column table.  Broad table queries still
    # receive the complete title/header/rows parent so column semantics and
    # the full comparison remain visible.
    if _model_keys(query) and selected_records and all(
        record.get("fields") for record in selected_records
    ):
        content_lines = [selected["title"].strip()] if selected["title"].strip() else []
        content_lines.extend(_render_record_fields(record) for record in selected_records)
        result["content"] = "\n\n".join(content_lines).strip()
    else:
        rendered = dict(selected)
        rendered["rows"] = selected_rows
        rendered["row_records"] = selected_records
        result["content"] = TableParent(**rendered).render()
    result["table_parent"] = True
    result["table_id"] = selected["table_id"]
    result["table_type"] = selected["table_type"]
    result["table_headers"] = selected["headers"]
    result["table_rows"] = selected_rows
    result["table_row_records"] = selected_records
    result["table_evidence_valid"] = bool(selected_records) and all(
        bool(record.get("validated")) for record in selected_records
    )
    return result
