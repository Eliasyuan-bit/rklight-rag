"""Convert RKVision ``document.json`` into LightRAG's sidecar IR."""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Any

from lightrag.sidecar.ir import IRBlock, IRDoc, IRPosition, IRTable


PREFACE_HEADING = "Preface/Uncategorized"
_TITLE_LABELS = {"title", "section_header"}
_TABLE_LABELS = {"table"}
_NUMBERED_HEADING = re.compile(r"^\s*(\d+(?:\.\d+)*)\s*[^\d.]?")
_LIST_HEADING = re.compile(r"^\s*(?:\d+|[A-Za-z])[）)]")


def _position(page_number: int, block: dict[str, Any]) -> IRPosition:
    box = block.get("box")
    valid_box = (
        isinstance(box, list)
        and len(box) == 4
        and all(isinstance(value, (int, float)) for value in box)
    )
    return IRPosition(
        type="bbox",
        anchor=str(page_number),
        range=list(box) if valid_box else None,
        origin="LEFTTOP",
    )


def _visible(block: dict[str, Any]) -> bool:
    text = str(block.get("text") or "").strip()
    if not text or not any(character.isalnum() for character in text):
        return False
    label = str(block.get("label") or "").casefold()
    source = str(block.get("text_source") or "").casefold()
    # Preserve native PDF text even when layout classifies it as furniture;
    # OCR-only figure/furniture text is normally UI chrome or page decoration.
    return not (source == "ocr" and label in {"figure", "abandon"})


def _table_rows(cells: list[dict[str, Any]]) -> list[list[str]]:
    """Reconstruct a simple grid from layout-labelled cell boxes.

    RKVision currently exposes text boxes rather than Docling's full cell
    topology.  Grouping by vertical centre preserves rows without inventing
    rowspan/colspan semantics; the original boxes remain in block provenance.
    """
    usable = []
    heights = []
    for cell in cells:
        box = cell.get("box")
        text = str(cell.get("text") or "").strip()
        if not text or not isinstance(box, list) or len(box) != 4:
            continue
        if not all(isinstance(value, (int, float)) for value in box):
            continue
        centre_y = (float(box[1]) + float(box[3])) / 2.0
        height = max(1.0, float(box[3]) - float(box[1]))
        usable.append((centre_y, float(box[0]), text))
        heights.append(height)
    if not usable:
        return []
    tolerance = max(4.0, statistics.median(heights) * 0.6)
    row_groups: list[list[tuple[float, float, str]]] = []
    for item in sorted(usable, key=lambda value: (value[0], value[1])):
        if not row_groups:
            row_groups.append([item])
            continue
        row_centre = sum(value[0] for value in row_groups[-1]) / len(row_groups[-1])
        if abs(item[0] - row_centre) <= tolerance:
            row_groups[-1].append(item)
        else:
            row_groups.append([item])
    return [
        [value[2] for value in sorted(row, key=lambda value: value[1])]
        for row in row_groups
    ]


def _is_structural_heading(text: str) -> bool:
    """Reject obvious list bullets and TOC leaders mislabelled as titles."""
    stripped = text.strip()
    return not stripped.startswith(("⚫", "◼", "•")) and stripped.count(".") < 8


def _list_style(text: str) -> str:
    match = _LIST_HEADING.match(text)
    if not match:
        return ""
    first = text.lstrip()[0]
    return "numeric" if first.isdigit() else "alpha"


def _heading_level(
    text: str,
    current_level: int,
    current_heading: str,
    heading_stack: dict[int, str],
    *,
    first: bool,
) -> int:
    """Infer a useful hierarchy from headings emitted by DocLayout-YOLO."""
    if first:
        return 0
    list_style = _list_style(text)
    if list_style:
        matching_levels = [
            level
            for level, heading in heading_stack.items()
            if _list_style(heading) == list_style
        ]
        if matching_levels:
            return max(matching_levels)
        if _list_style(current_heading) == list_style:
            return max(1, current_level)
        return min(6, max(1, current_level + 1))
    numbered = _NUMBERED_HEADING.match(text)
    if numbered:
        return min(6, numbered.group(1).count(".") + 1)
    if text.rstrip().endswith((":", "：")):
        return min(6, max(1, current_level + 1))
    return 1


class RkVisionIRBuilder:
    """Build sidecar blocks from audited page/layout output."""

    def normalize_from_path(self, path: Path, *, document_name: str) -> IRDoc:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"RKVision document JSON malformed at {path}: {exc}") from exc
        if not isinstance(document, dict):
            raise ValueError(f"RKVision document JSON is not an object at {path}")
        return self.normalize(document, document_name=document_name)

    def normalize(self, document: dict[str, Any], *, document_name: str) -> IRDoc:
        ir_blocks: list[IRBlock] = []
        current_heading = PREFACE_HEADING
        current_level = 0
        current_parents: list[str] = []
        heading_stack: dict[int, str] = {}
        doc_title = ""
        table_sequence = 0

        pages = document.get("pages") or []
        if not isinstance(pages, list):
            raise ValueError("RKVision document pages must be a list")

        for page_index, page in enumerate(pages, 1):
            if not isinstance(page, dict):
                continue
            page_number = int(page.get("page") or page_index)
            source_blocks = page.get("blocks") or []
            if not isinstance(source_blocks, list):
                continue
            ordered = sorted(
                (block for block in source_blocks if isinstance(block, dict)),
                key=lambda block: int(block.get("reading_order", 0) or 0),
            )
            index = 0
            while index < len(ordered):
                block = ordered[index]
                if not _visible(block):
                    index += 1
                    continue
                label = str(block.get("label") or "").casefold()
                text = str(block.get("text") or "").strip()

                if label in _TITLE_LABELS and _is_structural_heading(text):
                    level = _heading_level(
                        text,
                        current_level,
                        current_heading,
                        heading_stack,
                        first=not bool(doc_title),
                    )
                    parent_headings = [
                        heading_stack[parent_level]
                        for parent_level in sorted(heading_stack)
                        if parent_level < level
                    ]
                    heading_stack = {
                        parent_level: heading
                        for parent_level, heading in heading_stack.items()
                        if parent_level < level
                    }
                    heading_stack[level] = text
                    current_heading = text
                    current_level = level
                    current_parents = parent_headings
                    is_title_block = not bool(doc_title)
                    if not doc_title:
                        doc_title = text
                    ir_blocks.append(
                        IRBlock(
                            content_template=f"{'#' * max(1, level)} {text}",
                            heading=text,
                            level=level,
                            parent_headings=parent_headings,
                            is_title_block=is_title_block,
                            positions=[_position(page_number, block)],
                        )
                    )
                    index += 1
                    continue

                if label in _TABLE_LABELS:
                    table_cells = []
                    while index < len(ordered):
                        candidate = ordered[index]
                        if str(candidate.get("label") or "").casefold() not in _TABLE_LABELS:
                            break
                        if _visible(candidate):
                            table_cells.append(candidate)
                        index += 1
                    rows = _table_rows(table_cells)
                    if not rows:
                        continue
                    table_sequence += 1
                    placeholder = f"tb{table_sequence}"
                    ir_blocks.append(
                        IRBlock(
                            content_template=f"{{{{TBL:{placeholder}}}}}",
                            heading=current_heading,
                            level=current_level,
                            parent_headings=list(current_parents),
                            positions=[_position(page_number, cell) for cell in table_cells],
                            tables=[
                                IRTable(
                                    placeholder_key=placeholder,
                                    rows=rows,
                                    num_rows=len(rows),
                                    num_cols=max((len(row) for row in rows), default=0),
                                    table_header=[rows[0]] if len(rows) > 1 else None,
                                )
                            ],
                        )
                    )
                    continue

                ir_blocks.append(
                    IRBlock(
                        content_template=text,
                        heading=current_heading,
                        level=current_level,
                        parent_headings=list(current_parents),
                        positions=[_position(page_number, block)],
                    )
                )
                index += 1

        if not ir_blocks:
            raise ValueError("RKVision extracted no usable structured blocks")
        if not doc_title:
            doc_title = Path(document_name).stem or document_name
        return IRDoc(
            document_name=document_name,
            document_format=Path(document_name).suffix.lower().lstrip("."),
            doc_title=doc_title,
            split_option={
                "source": "rkvision_document_json",
                "page_count": int(document.get("page_count") or len(pages)),
            },
            blocks=ir_blocks,
            assets=[],
            bbox_attributes={"origin": "LEFTTOP"},
        )


__all__ = ["RkVisionIRBuilder"]
