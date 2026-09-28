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

from rk_table_parent import extract_table_parents, TableParent


def build(input_path: Path) -> dict[str, Any]:
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
            parent["child_rows"] = [
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
            parent["source_chunk_order"] = value.get("chunk_order_index")
            tables.append(parent)
            children.extend(parent["child_rows"])
    return {"version": 1, "tables": tables, "children": children}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = build(args.input)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"tables={len(result['tables'])} children={len(result['children'])} output={args.output}")


if __name__ == "__main__":
    main()
