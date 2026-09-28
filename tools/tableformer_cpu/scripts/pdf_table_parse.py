#!/usr/bin/env python3
"""Parse a mixed-content PDF and replace detected table regions with TableFormer output."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image


DEFAULT_DOCUMENT_VISION = "/userdata/document-vision-service"
DEFAULT_LAYOUT_MODEL = (
    "/userdata/doclayout-yolo-rknn-service/models/"
    "doclayout_yolo_640_logits_i8.rknn"
)
DEFAULT_OCR_MODELS = "/userdata/ppocrv6-rknn-service/models"


def env_path(name: str, default: str) -> str:
    return os.environ.get(name, default)


def run_checked(
    command: list[str], *, env: dict[str, str] | None = None, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        env=env,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{detail}")
    return result


def parse_daemon_response(stdout: str, request_id: str) -> dict[str, Any]:
    responses: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            responses.append(value)
    for response in responses:
        if response.get("id") == request_id:
            if not response.get("ok"):
                raise RuntimeError(str(response.get("error") or "document vision failed"))
            return response
    raise RuntimeError(f"document vision returned no response for {request_id}: {stdout}")


def run_document_vision(pdf: Path, output_dir: Path, dpi: int) -> dict[str, Any]:
    service_root = Path(env_path("TF_DOCUMENT_VISION_ROOT", DEFAULT_DOCUMENT_VISION))
    daemon = Path(
        env_path(
            "TF_DOCUMENT_VISION_DAEMON",
            str(service_root / "bin" / "document_vision_daemon"),
        )
    )
    layout_model = env_path("TF_LAYOUT_MODEL", DEFAULT_LAYOUT_MODEL)
    ocr_models = env_path("TF_OCR_MODELS", DEFAULT_OCR_MODELS)
    ocr_dict = env_path("TF_OCR_DICT", str(Path(ocr_models) / "ppocrv6_dict.txt"))
    request_id = f"tableformer-pdf-{os.getpid()}"
    request = json.dumps(
        {
            "id": request_id,
            "input": str(pdf),
            "output_dir": str(output_dir),
        },
        ensure_ascii=False,
    )
    process_env = os.environ.copy()
    libdir = str(service_root / "lib")
    process_env["LD_LIBRARY_PATH"] = libdir + (
        ":" + process_env["LD_LIBRARY_PATH"]
        if process_env.get("LD_LIBRARY_PATH")
        else ""
    )
    result = run_checked(
        [
            str(daemon),
            "--layout-model",
            layout_model,
            "--ocr-models",
            ocr_models,
            "--dict",
            ocr_dict,
            "--dpi",
            str(dpi),
        ],
        env=process_env,
        input_text=request + "\n",
    )
    return parse_daemon_response(result.stdout, request_id)


def box_area(box: list[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def intersection_area(a: list[float], b: list[float]) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1])
    )


def overlaps_table(block: dict[str, Any], table_box: list[float]) -> bool:
    box = block.get("box")
    if not isinstance(box, list) or len(box) != 4:
        return False
    try:
        candidate = [float(value) for value in box]
    except (TypeError, ValueError):
        return False
    area = box_area(candidate)
    if area <= 0:
        return False
    cx = (candidate[0] + candidate[2]) * 0.5
    cy = (candidate[1] + candidate[3]) * 0.5
    center_inside = (
        table_box[0] <= cx <= table_box[2]
        and table_box[1] <= cy <= table_box[3]
    )
    return center_inside or intersection_area(candidate, table_box) / area >= 0.5


def deduplicate_table_regions(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for region in regions:
        if str(region.get("label") or "").casefold() != "table":
            continue
        box = region.get("box")
        if not isinstance(box, list) or len(box) != 4:
            continue
        candidate = dict(region)
        candidate["box"] = [float(value) for value in box]
        candidates.append(candidate)
    candidates.sort(key=lambda item: float(item.get("layout_score") or 0), reverse=True)
    kept: list[dict[str, Any]] = []
    for candidate in candidates:
        duplicate = False
        for existing in kept:
            overlap = intersection_area(candidate["box"], existing["box"])
            smaller = min(box_area(candidate["box"]), box_area(existing["box"]))
            if smaller > 0 and overlap / smaller >= 0.85:
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)
    return sorted(kept, key=lambda item: (item["box"][1], item["box"][0]))


def padded_crop_box(box: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    padding = max(6, round(min(width, height) * 0.004))
    left = max(0, int(box[0]) - padding)
    top = max(0, int(box[1]) - padding)
    right = min(width, int(box[2] + 0.999) + padding)
    bottom = min(height, int(box[3] + 0.999) + padding)
    if right <= left or bottom <= top:
        raise ValueError(f"invalid table crop: {box}")
    return left, top, right, bottom


def cells_to_rows(cells: list[dict[str, Any]]) -> list[list[str]]:
    if not cells:
        return []
    row_count = max(int(cell.get("row", 0)) + int(cell.get("row_span", 1)) for cell in cells)
    col_count = max(int(cell.get("col", 0)) + int(cell.get("col_span", 1)) for cell in cells)
    rows = [["" for _ in range(col_count)] for _ in range(row_count)]
    for cell in cells:
        row = int(cell.get("row", 0))
        col = int(cell.get("col", 0))
        if 0 <= row < row_count and 0 <= col < col_count:
            rows[row][col] = str(cell.get("text") or "").strip()
    return rows


def cells_to_markdown(cells: list[dict[str, Any]]) -> str:
    rows = cells_to_rows(cells)
    if not rows:
        return ""
    lines = ["| " + " | ".join(value.replace("|", " ") for value in row) + " |" for row in rows]
    has_header = any(
        int(cell.get("row", -1)) == 0 and str(cell.get("label") or "") == "ched"
        for cell in cells
    )
    if has_header:
        lines.insert(1, "| " + " | ".join("---" for _ in rows[0]) + " |")
    return "\n".join(lines)


def map_cells_to_page(
    cells: list[dict[str, Any]], crop: tuple[int, int, int, int]
) -> list[dict[str, Any]]:
    left, top, right, bottom = crop
    width = right - left
    height = bottom - top
    mapped: list[dict[str, Any]] = []
    for source in cells:
        cell = dict(source)
        box = cell.get("bbox")
        if isinstance(box, list) and len(box) == 4:
            cell["page_box"] = [
                left + float(box[0]) * width,
                top + float(box[1]) * height,
                left + float(box[2]) * width,
                top + float(box[3]) * height,
            ]
        mapped.append(cell)
    return mapped


def fill_cells_from_native_glyphs(
    cells: list[dict[str, Any]], glyphs: Any
) -> int:
    """Replace OCR cell text with exact PDF glyphs when a text layer exists."""
    if not isinstance(glyphs, list) or not cells:
        return 0
    assignments: list[list[tuple[int, dict[str, Any]]]] = [[] for _ in cells]
    for glyph_index, glyph in enumerate(glyphs):
        if not isinstance(glyph, dict) or not str(glyph.get("text") or ""):
            continue
        glyph_box = glyph.get("box")
        if not isinstance(glyph_box, list) or len(glyph_box) != 4:
            continue
        try:
            candidate_box = [float(value) for value in glyph_box]
        except (TypeError, ValueError):
            continue
        center_x = (candidate_box[0] + candidate_box[2]) * 0.5
        center_y = (candidate_box[1] + candidate_box[3]) * 0.5
        best_cell = -1
        best_overlap = 0.0
        for cell_index, cell in enumerate(cells):
            page_box = cell.get("page_box")
            if not isinstance(page_box, list) or len(page_box) != 4:
                continue
            box = [float(value) for value in page_box]
            overlap = intersection_area(candidate_box, box)
            center_inside = box[0] <= center_x <= box[2] and box[1] <= center_y <= box[3]
            if center_inside and overlap >= best_overlap:
                best_cell = cell_index
                best_overlap = overlap
            elif best_cell < 0 and overlap > best_overlap:
                best_cell = cell_index
                best_overlap = overlap
        if best_cell >= 0:
            assignments[best_cell].append((glyph_index, glyph))

    replaced = 0
    for cell, selected in zip(cells, assignments):
        if not selected:
            cell["text_source"] = "ocr"
            continue
        output = ""
        previous_box: list[float] | None = None
        for _, glyph in sorted(selected, key=lambda item: item[0]):
            text = str(glyph.get("text") or "")
            box = [float(value) for value in glyph["box"]]
            line_break = False
            if previous_box is not None:
                previous_height = max(1.0, previous_box[3] - previous_box[1])
                height = max(1.0, box[3] - box[1])
                previous_y = (previous_box[1] + previous_box[3]) * 0.5
                current_y = (box[1] + box[3]) * 0.5
                line_break = abs(current_y - previous_y) > max(previous_height, height) * 0.65
            needs_separator = bool(glyph.get("space_before")) or line_break
            # A PDF may wrap an ISO date or hyphenated word immediately after
            # the hyphen.  Rejoining that visual line must not invent a space.
            if line_break and output.endswith("-"):
                needs_separator = False
            if output and not output.endswith((" ", "\n")) and needs_separator:
                output += " "
            output += text
            previous_box = box
        native_text = " ".join(output.split())
        if native_text:
            cell["ocr_text"] = str(cell.get("text") or "")
            cell["text"] = native_text
            cell["text_source"] = "pdfium"
            replaced += 1
        else:
            cell["text_source"] = "ocr"
    return replaced


def render_page(pdf: Path, page_number: int, dpi: int, output: Path) -> None:
    service_root = Path(env_path("TF_DOCUMENT_VISION_ROOT", DEFAULT_DOCUMENT_VISION))
    binary = Path(env_path("TF_PDFIUM_PAGE", str(service_root / "bin" / "pdfium_page")))
    process_env = os.environ.copy()
    libdir = str(service_root / "lib")
    process_env["LD_LIBRARY_PATH"] = libdir + (
        ":" + process_env["LD_LIBRARY_PATH"]
        if process_env.get("LD_LIBRARY_PATH")
        else ""
    )
    run_checked(
        [
            str(binary),
            "--input",
            str(pdf),
            "--page",
            str(page_number),
            "--render",
            str(output),
            "--dpi",
            str(dpi),
        ],
        env=process_env,
    )


def parse_table_crop(
    crop_path: Path,
    markdown_path: Path,
    max_steps: int,
) -> tuple[str, list[dict[str, Any]], str, float]:
    root = Path(env_path("TF_TABLEFORMER_ROOT", str(Path(__file__).resolve().parent)))
    runner = Path(env_path("TF_TABLEFORMER_RUNNER", str(root / "run.sh")))
    started = time.monotonic()
    result = run_checked(
        [str(runner), str(crop_path), str(markdown_path), str(max_steps)]
    )
    elapsed_ms = (time.monotonic() - started) * 1000.0
    markdown = markdown_path.read_text(encoding="utf-8").strip()
    cells_path = Path(str(markdown_path) + ".cells.json")
    cells = json.loads(cells_path.read_text(encoding="utf-8"))
    if not markdown or not isinstance(cells, list) or not cells:
        raise RuntimeError("TableFormer produced an empty table")
    return markdown, cells, result.stdout + result.stderr, elapsed_ms


def table_order(page: dict[str, Any], table_box: list[float]) -> int:
    matching = [
        int(block.get("reading_order", 0) or 0)
        for block in page.get("blocks") or []
        if isinstance(block, dict) and overlaps_table(block, table_box)
    ]
    if matching:
        return min(matching)
    above = 0
    for block in page.get("blocks") or []:
        box = block.get("box") if isinstance(block, dict) else None
        if isinstance(box, list) and len(box) == 4 and float(box[1]) < table_box[1]:
            above += 1
    return above


def build_enriched_markdown(document: dict[str, Any]) -> str:
    lines: list[str] = []
    for page in document.get("pages") or []:
        page_number = int(page.get("page") or 0)
        lines.extend([f"# Page {page_number}", ""])
        tables = [
            table
            for table in page.get("tables") or []
            if table.get("status") == "ok" and str(table.get("markdown") or "").strip()
        ]
        events: list[tuple[int, int, str]] = []
        for index, block in enumerate(page.get("blocks") or []):
            if not isinstance(block, dict):
                continue
            if any(overlaps_table(block, table["box"]) for table in tables):
                continue
            text = str(block.get("text") or "").strip()
            if not text:
                continue
            if (
                str(block.get("label") or "").casefold() == "figure"
                and str(block.get("text_source") or "").casefold() == "ocr"
            ):
                continue
            label = str(block.get("label") or "").casefold()
            if label in {"title", "section_header"}:
                text = f"## {text}"
            elif label == "table_caption":
                text = f"### {text}"
            order = int(block.get("reading_order", index) or 0)
            events.append((order, 1, text))
        for table in tables:
            events.append((int(table.get("reading_order", 0)), 0, str(table["markdown"])))
        for _, _, content in sorted(events, key=lambda value: (value[0], value[1])):
            lines.extend([content, ""])
    return "\n".join(lines).rstrip() + "\n"


def process_pdf(args: argparse.Namespace) -> dict[str, Any]:
    pdf = args.input.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not pdf.is_file():
        raise FileNotFoundError(pdf)

    started = time.monotonic()
    if args.document_json:
        source_document_path = args.document_json.resolve()
        document_path = output_dir / "document.json"
        shutil.copy2(source_document_path, output_dir / "document.raw.json")
        if source_document_path != document_path:
            shutil.copy2(source_document_path, document_path)
    else:
        run_document_vision(pdf, output_dir, args.dpi)
        document_path = output_dir / "document.json"
        if (output_dir / "document.md").exists():
            shutil.copy2(output_dir / "document.md", output_dir / "document.raw.md")
        shutil.copy2(document_path, output_dir / "document.raw.json")

    document = json.loads(document_path.read_text(encoding="utf-8"))
    assets = output_dir / "tables"
    assets.mkdir(parents=True, exist_ok=True)
    table_count = 0
    success_count = 0
    failure_count = 0

    for page in document.get("pages") or []:
        page_number = int(page.get("page") or 0)
        regions = deduplicate_table_regions(page.get("layout_regions") or [])
        page["tables"] = []
        if not regions:
            continue
        page_image = assets / f"page-{page_number:03d}.png"
        render_page(pdf, page_number, args.dpi, page_image)
        with Image.open(page_image) as image:
            width, height = image.size
            for table_index, region in enumerate(regions, 1):
                table_count += 1
                table_id = f"page-{page_number:03d}-table-{table_index:02d}"
                crop_box = padded_crop_box(region["box"], width, height)
                crop_path = assets / f"{table_id}.png"
                markdown_path = assets / f"{table_id}.md"
                image.crop(crop_box).save(crop_path)
                record: dict[str, Any] = {
                    "id": table_id,
                    "page": page_number,
                    "box": region["box"],
                    "crop_box": list(crop_box),
                    "layout_score": float(region.get("layout_score") or 0),
                    "reading_order": table_order(page, region["box"]),
                }
                try:
                    markdown, cells, log, elapsed_ms = parse_table_crop(
                        crop_path, markdown_path, args.max_steps
                    )
                    mapped_cells = map_cells_to_page(cells, crop_box)
                    native_cell_count = fill_cells_from_native_glyphs(
                        mapped_cells, page.get("native_glyphs")
                    )
                    if native_cell_count:
                        markdown = cells_to_markdown(mapped_cells)
                        markdown_path.write_text(markdown + "\n", encoding="utf-8")
                        Path(str(markdown_path) + ".cells.json").write_text(
                            json.dumps(mapped_cells, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8",
                        )
                    record.update(
                        {
                            "status": "ok",
                            "markdown": markdown,
                            "rows": cells_to_rows(mapped_cells),
                            "cells": mapped_cells,
                            "native_cell_count": native_cell_count,
                            "ocr_cell_count": len(mapped_cells) - native_cell_count,
                            "elapsed_ms": round(elapsed_ms, 3),
                            "log": log.strip(),
                        }
                    )
                    success_count += 1
                except Exception as error:  # keep lossless text fallback per table
                    record.update({"status": "fallback", "error": str(error)})
                    failure_count += 1
                page["tables"].append(record)
        if not args.keep_page_images:
            page_image.unlink(missing_ok=True)

    document["tableformer"] = {
        "table_count": table_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "dpi": args.dpi,
        "max_steps": args.max_steps,
    }
    document_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "document.md").write_text(
        build_enriched_markdown(document), encoding="utf-8"
    )
    elapsed_ms = round((time.monotonic() - started) * 1000.0, 3)
    summary = {
        # A failed individual table deliberately falls back to the original
        # lossless page blocks, so the document-level operation still succeeds.
        "ok": True,
        "all_tables_restored": failure_count == 0,
        "input": str(pdf),
        "output_dir": str(output_dir),
        "page_count": int(document.get("page_count") or len(document.get("pages") or [])),
        "table_count": table_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "elapsed_ms": elapsed_ms,
    }
    (output_dir / "tableformer-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse a mixed-content PDF and restore detected tables with TableFormer."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--max-steps", type=int, default=256)
    parser.add_argument("--document-json", type=Path)
    parser.add_argument("--keep-page-images", action="store_true")
    return parser.parse_args()


def main() -> int:
    try:
        summary = process_pdf(parse_args())
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if summary["ok"] else 1
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
