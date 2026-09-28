#!/usr/bin/env python3
"""Build a persistent parent/child table index from LightRAG text chunks.

Usage:
  python3 build_table_parent_index.py chunks.json table_parent_index.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rk_table_parent import extract_table_parents, table_from_structured_sidecar, TableParent


def _child_rows(parent: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "table_id": parent["table_id"],
            "source_chunk_id": parent["source_chunk_id"],
            "content": "\n".join(
                part for part in (parent["title"], " | ".join(parent["headers"]), row) if part
            ),
            "table_type": parent["table_type"],
            "source_file": parent["source_file"],
            "row_index": row_index,
            "row": row,
            "fields": parent.get("row_records", [])[row_index].get("fields", {})
            if row_index < len(parent.get("row_records", [])) else {},
            "model_key": parent.get("row_records", [])[row_index].get("model_key", "")
            if row_index < len(parent.get("row_records", [])) else "",
        }
        for row_index, row in enumerate(parent["rows"])
    ]


def _sidecar_tables(parsed_root: Path, chunks: dict[str, Any]) -> list[dict[str, Any]]:
    """Read parser-provided table schemas; never infer a business table type."""
    chunk_for_table_id = {
        table_id: str(chunk_id)
        for chunk_id, value in chunks.items() if isinstance(value, dict)
        for table_id in __import__("re").findall(r'<table\s+id=["\']([^"\']+)', str(value.get("content") or ""))
    }
    parents: list[dict[str, Any]] = []
    for path in parsed_root.rglob("*.tables.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        table_map = raw.get("tables", raw)
        if not isinstance(table_map, dict):
            continue
        for table_id, item in table_map.items():
            if not isinstance(item, dict):
                continue
            try:
                headers = json.loads(str(item.get("table_header") or "[]"))
                rows = json.loads(str(item.get("content") or "[]"))
            except json.JSONDecodeError:
                continue
            if not (isinstance(headers, list) and headers and isinstance(headers[0], list) and isinstance(rows, list)):
                continue
            title_parts = [str(value).strip() for value in item.get("parent_headings") or [] if str(value).strip()]
            if str(item.get("heading") or "").strip():
                title_parts.append(str(item["heading"]).strip())
            parent = table_from_structured_sidecar(
                table_id=str(table_id), title=" > ".join(title_parts), headers=headers[0], rows=rows,
                source_chunk_id=chunk_for_table_id.get(str(table_id), ""),
                source_file=path.name.removesuffix(".tables.json").removesuffix(".parsed"),
            )
            parents.append(parent)
    return parents


def build(input_path: Path, parsed_root: Path | None = None) -> dict[str, Any]:
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("text chunk store must be a JSON object")
    tables: list[dict[str, Any]] = []
    children: list[dict[str, Any]] = []
    for chunk_id, value in raw.items():
        if not isinstance(value, dict):
            continue
        content = str(value.get("content") or "")
        if not content:
            continue
        parents = extract_table_parents(
            content,
            chunk_id=str(chunk_id),
            source_file=str(value.get("file_path") or value.get("source_file") or ""),
        )
        for parent in parents:
            parent["parent_content"] = TableParent(**parent).render()
            parent["child_rows"] = _child_rows(parent)
            parent["source_chunk_order"] = value.get("chunk_order_index")
            tables.append(parent)
            children.extend(parent["child_rows"])
    if parsed_root and parsed_root.is_dir():
        existing_ids = {str(table["table_id"]) for table in tables}
        for parent in _sidecar_tables(parsed_root, raw):
            if parent["table_id"] in existing_ids:
                continue
            parent["parent_content"] = TableParent(**parent).render()
            parent["child_rows"] = _child_rows(parent)
            tables.append(parent)
            children.extend(parent["child_rows"])
    return {"version": 2, "tables": tables, "children": children}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--parsed-root", type=Path)
    args = parser.parse_args()
    result = build(args.input, args.parsed_root)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"tables={len(result['tables'])} children={len(result['children'])} output={args.output}")


if __name__ == "__main__":
    main()
