#!/usr/bin/env python3
"""Split Markdown into LightRAG KG and text-only ingestion sources.

The output filenames carry LightRAG's native parser hints:

* ``.[-P].md``  -- paragraph-semantic chunks and entity/relation extraction.
* ``.[-P!].md`` -- the same chunks/indexes, but no entity/relation extraction.

Nothing is discarded: the text-only source remains available to BM25/vector
retrieval.  This is deliberately a small, deterministic pre-ingestion layer;
it does not replace LightRAG's parser or index pipeline.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
TABLE_DELIMITER_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")
LOG_LINE_RE = re.compile(
    r"(?:^|\s)(?:\d{4}-\d\d-\d\d|\d\d:\d\d:\d\d|DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|Traceback|Exception|"
    r"kernel:|dmesg:|\[[0-9.]+\])",
    re.IGNORECASE,
)
SHELL_LINE_RE = re.compile(r"^\s*(?:[$#]|sudo\s+|adb\s+|curl\s+|python(?:3)?\s+|export\s+|systemctl\s+)")

# Whole sections where the content is useful for exact retrieval but produces
# low-value/noisy graph entities and relations.
TEXT_ONLY_HEADING_RE = re.compile(
    r"(?:目录|修订记录|更新记录|版本(?:信息|记录|历史)?|变更记录|参考(?:文献|资料)?|附录|"
    r"文件清单|命令清单|参数(?:表|列表|配置表)|术语表|索引|copyright|revision|changelog|"
    r"references?|appendix|table\s+of\s+contents)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Block:
    text: str
    heading_path: tuple[tuple[int, str], ...]
    kind: str
    reason: str


def _heading_path_prefix(path: tuple[tuple[int, str], ...], emitted: tuple[tuple[int, str], ...]) -> str:
    """Return the headings needed to give a destination block its context."""
    shared = 0
    for old, new in zip(emitted, path):
        if old != new:
            break
        shared += 1
    return "\n".join("#" * level + " " + title for level, title in path[shared:])


def _is_table(lines: list[str]) -> bool:
    return len(lines) >= 2 and TABLE_DELIMITER_RE.match(lines[1]) is not None


def _is_log(lines: list[str]) -> bool:
    nonempty = [line for line in lines if line.strip()]
    if not nonempty:
        return False
    hits = sum(bool(LOG_LINE_RE.search(line)) for line in nonempty)
    return hits >= max(2, len(nonempty) // 2)


def _is_command_list(lines: list[str]) -> bool:
    nonempty = [line for line in lines if line.strip()]
    if not nonempty:
        return False
    hits = sum(bool(SHELL_LINE_RE.match(line)) for line in nonempty)
    return hits >= max(2, len(nonempty) // 2)


def _classify(lines: list[str], heading_path: tuple[tuple[int, str], ...], in_fence: bool) -> tuple[str, str]:
    heading_text = " / ".join(title for _, title in heading_path)
    if TEXT_ONLY_HEADING_RE.search(heading_text):
        return "text", "low_value_section"
    if in_fence:
        return "text", "fenced_code_or_mermaid"
    if _is_table(lines):
        return "text", "markdown_table"
    if _is_log(lines):
        return "text", "raw_log"
    if _is_command_list(lines):
        return "text", "command_list"
    return "kg", "semantic_prose"


def parse_markdown(markdown: str) -> list[Block]:
    """Split a Markdown document into heading-scoped semantic blocks."""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    headings: list[tuple[int, str]] = []
    pending: list[str] = []
    in_fence = False

    def flush() -> None:
        nonlocal pending
        while pending and not pending[0].strip():
            pending.pop(0)
        while pending and not pending[-1].strip():
            pending.pop()
        if pending:
            kind, reason = _classify(pending, tuple(headings), in_fence)
            blocks.append(Block("\n".join(pending), tuple(headings), kind, reason))
        pending = []

    index = 0
    while index < len(lines):
        line = lines[index]
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            # A fenced section is indivisible even when it includes blank lines.
            flush()
            fence = [line]
            marker = line.lstrip()[:3]
            index += 1
            while index < len(lines):
                fence.append(lines[index])
                if lines[index].lstrip().startswith(marker):
                    index += 1
                    break
                index += 1
            kind, reason = _classify(fence, tuple(headings), True)
            blocks.append(Block("\n".join(fence), tuple(headings), kind, reason))
            continue

        match = HEADING_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            headings = [item for item in headings if item[0] < level]
            headings.append((level, title))
            index += 1
            continue

        # Keep a whole Markdown table together.
        if index + 1 < len(lines) and "|" in line and TABLE_DELIMITER_RE.match(lines[index + 1]):
            flush()
            table = [line, lines[index + 1]]
            index += 2
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                table.append(lines[index])
                index += 1
            kind, reason = _classify(table, tuple(headings), False)
            blocks.append(Block("\n".join(table), tuple(headings), kind, reason))
            continue

        if not line.strip() and pending:
            flush()
        else:
            pending.append(line)
        index += 1
    flush()
    return blocks


def render(blocks: Iterable[Block], desired_kind: str, original_name: str) -> str:
    output = [f"<!-- source: {original_name}; route: {'kg' if desired_kind == 'kg' else 'text-only'} -->"]
    last_path: tuple[tuple[int, str], ...] = ()
    for block in blocks:
        if block.kind != desired_kind:
            continue
        prefix = _heading_path_prefix(block.heading_path, last_path)
        if prefix:
            output.extend(("", prefix))
        output.extend(("", block.text))
        last_path = block.heading_path
    return "\n".join(output).strip() + "\n"


def route_markdown_file(source: Path, output_dir: Path) -> tuple[list[Path], Path, dict]:
    """Route one Markdown source for LightRAG's native ``P`` / ``P!`` paths.

    ``outputs`` contains only non-empty routed documents.  The manifest is
    deliberately stored outside LightRAG's input directory by the caller: it
    is audit data, not a document to index.
    """
    source = source.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    blocks = parse_markdown(source.read_text(encoding="utf-8"))
    stem = source.stem
    kg_path = output_dir / f"{stem}.kg.[-P].md"
    text_path = output_dir / f"{stem}.text.[-P!].md"
    manifest_path = output_dir / f"{stem}.route.json"

    rendered = {
        "kg": render(blocks, "kg", source.name),
        "text_only": render(blocks, "text", source.name),
    }
    outputs: list[Path] = []
    for kind, path in (("kg", kg_path), ("text_only", text_path)):
        # The route comment alone is not useful content; avoid creating an
        # empty P/P! document when a source has only the opposite category.
        if any(block.kind == ("kg" if kind == "kg" else "text") for block in blocks):
            path.write_text(rendered[kind], encoding="utf-8")
            outputs.append(path)

    counts: dict[str, int] = {}
    for block in blocks:
        counts[block.reason] = counts.get(block.reason, 0) + 1
    manifest = {
        "source": str(source),
        "outputs": {"kg": str(kg_path) if kg_path in outputs else None,
                    "text_only": str(text_path) if text_path in outputs else None},
        "process_options": {"kg": "P", "text_only": "P!"},
        "block_counts": {
            "total": len(blocks),
            "kg": sum(block.kind == "kg" for block in blocks),
            "text_only": sum(block.kind == "text" for block in blocks),
        },
        "reasons": counts,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return outputs, manifest_path, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Route Markdown into LightRAG KG and text-only sources")
    parser.add_argument("input", type=Path, help="Markdown input, normally document.md from the parser")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    source = args.input.resolve()
    if not source.is_file():
        raise SystemExit(f"input does not exist: {source}")
    _, _, manifest = route_markdown_file(source, args.output_dir)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
