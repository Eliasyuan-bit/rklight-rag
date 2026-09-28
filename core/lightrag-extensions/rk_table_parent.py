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


class TableParent:
    def __init__(self, table_id: str, title: str, headers: list[str], rows: list[str],
                 table_type: str, source_chunk_id: str = "", source_file: str = ""):
        self.table_id = table_id
        self.title = title
        self.headers = headers
        self.rows = rows
        self.table_type = table_type
        self.source_chunk_id = source_chunk_id
        self.source_file = source_file

    def render(self) -> str:
        parts = [self.title.strip()] if self.title.strip() else []
        if self.table_type == "llm_performance":
            # Docling's plain-text PDF export often flattens this header into
            # one token stream.  Preserve the source values, but restore its
            # public schema so the answer model cannot shift TTFT into TPS.
            columns = [
                "Model Name",
                "Accelerator",
                "Input Tokens",
                "New Tokens",
                "TTFT (ms)",
                "TPOT (ms)",
                "Decode TPS",
            ]
            parts.extend((
                "| " + " | ".join(columns) + " |",
                "| " + " | ".join("---" for _ in columns) + " |",
            ))
            for row in self.rows:
                cells = row.strip().split()
                if len(cells) == len(columns):
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
        }


def classify_table_type(title: str, headers: list[str], body: str) -> str:
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
    result = chunk.copy()
    result["content"] = TableParent(**selected).render()
    result["table_parent"] = True
    result["table_id"] = selected["table_id"]
    result["table_type"] = selected["table_type"]
    result["table_headers"] = selected["headers"]
    result["table_rows"] = selected["rows"]
    return result
