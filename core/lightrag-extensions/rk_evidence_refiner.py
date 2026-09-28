"""Structure-aware, post-retrieval evidence refinement for small generators."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LIST_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？；!?])|(?<=[A-Za-z0-9][.!?])\s+")
_BROAD_QUERY_TERMS = (
    "介绍",
    "完整",
    "全部",
    "整体",
    "流程",
    "步骤",
    "包括哪些",
    "具体内容",
)


def _enabled() -> bool:
    return os.getenv("RK_EVIDENCE_REFINER_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _split_sentences(text: str) -> list[str]:
    compact = " ".join(part.strip() for part in text.splitlines() if part.strip())
    if not compact:
        return []
    parts = [part.strip() for part in _SENTENCE_BOUNDARY_RE.split(compact)]
    parts = [part for part in parts if part]
    # Very small fragments are usually labels or sentence tails. Keeping the
    # paragraph intact is safer than sending meaningless units to the ranker.
    if len(parts) > 1 and any(len(part) < 12 for part in parts):
        return [compact]
    return parts


def split_evidence_units(content: str) -> list[dict[str, Any]]:
    """Split Markdown-like text into coherent, source-addressable units."""
    lines = content.splitlines()
    units: list[dict[str, Any]] = []
    headings: list[tuple[int, str, str]] = []
    paragraph: list[str] = []
    index = 0

    def section_data() -> tuple[str, str]:
        if not headings:
            return "", ""
        return " > ".join(item[1] for item in headings), headings[-1][2]

    def add(text: str, kind: str, *, table_header: str = "") -> None:
        nonlocal index
        text = text.strip()
        if not text:
            return
        section_path, heading = section_data()
        start = content.find(text)
        units.append(
            {
                "index": index,
                "text": text,
                "kind": kind,
                "section_path": section_path,
                "heading": heading,
                "table_header": table_header,
                "start": start,
                "end": start + len(text) if start >= 0 else -1,
            }
        )
        index += 1

    def flush_paragraph() -> None:
        if not paragraph:
            return
        value = "\n".join(paragraph).strip()
        paragraph.clear()
        for sentence in _split_sentences(value):
            add(sentence, "sentence")

    line_index = 0
    while line_index < len(lines):
        line = lines[line_index]
        stripped = line.strip()
        heading_match = _HEADING_RE.match(stripped)
        if heading_match:
            flush_paragraph()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            headings[:] = [item for item in headings if item[0] < level]
            headings.append((level, title, stripped))
            line_index += 1
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            flush_paragraph()
            fence = stripped[:3]
            block = [line]
            line_index += 1
            while line_index < len(lines):
                block.append(lines[line_index])
                if lines[line_index].strip().startswith(fence):
                    line_index += 1
                    break
                line_index += 1
            add("\n".join(block), "code")
            continue
        if "<table" in stripped.casefold():
            flush_paragraph()
            block = [line]
            line_index += 1
            while line_index < len(lines) and "</table>" not in "\n".join(block).casefold():
                block.append(lines[line_index])
                line_index += 1
            table_text = "\n".join(block)
            json_table = re.search(
                r'(<table\b[^>]*\bformat=["\']json["\'][^>]*>)(.*?)</table>',
                table_text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if json_table:
                try:
                    rows = json.loads(json_table.group(2))
                except (json.JSONDecodeError, TypeError):
                    rows = None
                if isinstance(rows, list) and all(isinstance(row, list) for row in rows):
                    for row in rows:
                        add(
                            json.dumps(row, ensure_ascii=False),
                            "json_table_row",
                            table_header=json_table.group(1),
                        )
                    continue
            add(table_text, "table")
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_paragraph()
            table_lines = []
            while line_index < len(lines):
                candidate = lines[line_index].strip()
                if not (candidate.startswith("|") and candidate.endswith("|")):
                    break
                table_lines.append(candidate)
                line_index += 1
            if len(table_lines) <= 2:
                add("\n".join(table_lines), "table")
            else:
                header = "\n".join(table_lines[:2])
                for row in table_lines[2:]:
                    add(row, "table_row", table_header=header)
            continue
        if _LIST_RE.match(line):
            flush_paragraph()
            block = [line]
            line_index += 1
            while line_index < len(lines):
                continuation = lines[line_index]
                if not continuation.strip():
                    break
                if _HEADING_RE.match(continuation.strip()) or _LIST_RE.match(continuation):
                    break
                if continuation.startswith((" ", "\t")):
                    block.append(continuation)
                    line_index += 1
                    continue
                break
            add("\n".join(block), "list_item")
            continue
        if not stripped:
            flush_paragraph()
            line_index += 1
            continue
        paragraph.append(line)
        line_index += 1

    flush_paragraph()
    return units


def _rerank_endpoint() -> str:
    return os.getenv("RERANK_BINDING_HOST", "http://127.0.0.1:8100/v1/rerank")


def _request_rerank(query: str, documents: list[str]) -> list[float]:
    payload = json.dumps(
        {
            "model": os.getenv("RERANK_MODEL", "qwen3-reranker-0.6b"),
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        _rerank_endpoint(),
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer "
            + os.getenv("RERANK_BINDING_API_KEY", "local-no-key"),
        },
        method="POST",
    )
    timeout = float(os.getenv("RK_EVIDENCE_RERANK_TIMEOUT", "60"))
    with urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read())
    scores = [0.0] * len(documents)
    for item in result.get("results", []):
        position = int(item["index"])
        if 0 <= position < len(scores):
            scores[position] = float(item["relevance_score"])
    return scores


def _rank_text(unit: dict[str, Any]) -> str:
    prefix = []
    if unit.get("section_path"):
        prefix.append("Section: " + str(unit["section_path"]))
    prefix.append("Evidence type: " + str(unit["kind"]))
    prefix.append(str(unit["text"]))
    return "\n".join(prefix)


def _reconstruct(units: list[dict[str, Any]]) -> str:
    output: list[str] = []
    emitted_headings: set[str] = set()
    emitted_table_headers: set[str] = set()
    for unit in sorted(units, key=lambda value: int(value["index"])):
        heading = str(unit.get("heading") or "")
        if heading and heading not in emitted_headings:
            output.append(heading)
            emitted_headings.add(heading)
        table_header = str(unit.get("table_header") or "")
        if unit.get("kind") == "json_table_row" and table_header:
            output.append(f"{table_header}[{unit['text']}]</table>")
            continue
        if table_header and table_header not in emitted_table_headers:
            output.append(table_header)
            emitted_table_headers.add(table_header)
        output.append(str(unit["text"]))
    return "\n\n".join(output).strip()


async def refine_evidence_units(
    chunks: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """Rerank evidence inside retrieved chunks and rebuild a compact context."""
    if not _enabled() or not query.strip() or not chunks:
        return chunks

    min_chars = max(0, int(os.getenv("RK_EVIDENCE_MIN_TOTAL_CHARS", "240")))
    if sum(len(str(chunk.get("content") or "")) for chunk in chunks) < min_chars:
        return chunks

    max_candidates = max(1, int(os.getenv("RK_EVIDENCE_MAX_CANDIDATES", "24")))
    max_per_chunk = max(1, int(os.getenv("RK_EVIDENCE_MAX_UNITS_PER_CHUNK", "8")))
    candidates: list[dict[str, Any]] = []
    for chunk_index, chunk in enumerate(chunks):
        units = split_evidence_units(str(chunk.get("content") or ""))
        # A verbose top passage must not consume the whole candidate budget;
        # preserve coverage across the already reranked chunk list.
        for unit in units[:max_per_chunk]:
            candidate = unit.copy()
            candidate["chunk_index"] = chunk_index
            candidates.append(candidate)
            if len(candidates) >= max_candidates:
                break
        if len(candidates) >= max_candidates:
            break

    minimum_units = max(2, int(os.getenv("RK_EVIDENCE_MIN_UNITS", "3")))
    if len(candidates) < minimum_units:
        return chunks

    try:
        scores = await asyncio.to_thread(
            _request_rerank, query, [_rank_text(unit) for unit in candidates]
        )
    except Exception as exc:  # preserve the original context on infrastructure failure
        logger.warning("Evidence refinement failed; using original chunks: %s", exc)
        return chunks
    if len(scores) != len(candidates) or not scores:
        return chunks

    for unit, score in zip(candidates, scores):
        unit["score"] = float(score)
    best_score = max(scores)
    minimum_score = float(os.getenv("RK_EVIDENCE_MIN_SCORE", "0.1"))
    relative_ratio = float(os.getenv("RK_EVIDENCE_RELATIVE_SCORE_RATIO", "0.5"))
    if any(term in query for term in _BROAD_QUERY_TERMS):
        relative_ratio = float(os.getenv("RK_EVIDENCE_BROAD_SCORE_RATIO", "0.3"))
    score_floor = max(minimum_score, best_score * relative_ratio)

    selected_keys = {
        (int(unit["chunk_index"]), int(unit["index"]))
        for unit in candidates
        if float(unit["score"]) >= score_floor
    }
    if not selected_keys:
        best = max(candidates, key=lambda unit: float(unit["score"]))
        selected_keys.add((int(best["chunk_index"]), int(best["index"])))

    # A query-aware sparse+dense fusion may reserve one direct lexical
    # passage. Keep its best evidence unit while still allowing the refiner to
    # remove unrelated sentences from the rest of that chunk.
    for chunk_index, chunk in enumerate(chunks):
        if not chunk.get("exact_retrieval_protected"):
            continue
        protected = [
            unit for unit in candidates if int(unit["chunk_index"]) == chunk_index
        ]
        if protected:
            best = max(protected, key=lambda unit: float(unit["score"]))
            selected_keys.add((chunk_index, int(best["index"])))

    # Small-to-big restoration: admit adjacent evidence only when it has its
    # own relevance signal and belongs to the same structural section.
    neighbour_ratio = float(os.getenv("RK_EVIDENCE_NEIGHBOR_SCORE_RATIO", "0.35"))
    neighbour_floor = max(minimum_score, best_score * neighbour_ratio)
    candidate_map = {
        (int(unit["chunk_index"]), int(unit["index"])): unit for unit in candidates
    }
    for chunk_index, unit_index in list(selected_keys):
        selected = candidate_map[(chunk_index, unit_index)]
        for neighbour_index in (unit_index - 1, unit_index + 1):
            neighbour = candidate_map.get((chunk_index, neighbour_index))
            if not neighbour:
                continue
            if neighbour.get("section_path") != selected.get("section_path"):
                continue
            if float(neighbour["score"]) >= neighbour_floor:
                selected_keys.add((chunk_index, neighbour_index))

    max_units = max(1, int(os.getenv("RK_EVIDENCE_MAX_UNITS", "12")))
    ranked_selected = sorted(
        (candidate_map[key] for key in selected_keys),
        key=lambda unit: float(unit["score"]),
        reverse=True,
    )[:max_units]

    max_chars = max(256, int(os.getenv("RK_EVIDENCE_MAX_CHARS", "6000")))
    admitted: list[dict[str, Any]] = []
    used_chars = 0
    for unit in ranked_selected:
        size = len(str(unit["text"])) + len(str(unit.get("heading") or ""))
        if admitted and used_chars + size > max_chars:
            continue
        admitted.append(unit)
        used_chars += size

    refined: list[dict[str, Any]] = []
    for chunk_index, chunk in enumerate(chunks):
        selected = [
            unit for unit in admitted if int(unit["chunk_index"]) == chunk_index
        ]
        if not selected:
            continue
        item = chunk.copy()
        item["content"] = _reconstruct(selected)
        item["evidence_refined"] = True
        item["evidence_unit_count"] = len(selected)
        item["evidence_unit_scores"] = [
            round(float(unit["score"]), 6) for unit in selected
        ]
        item["evidence_ranges"] = [
            [int(unit["start"]), int(unit["end"])]
            for unit in sorted(selected, key=lambda value: int(value["index"]))
            if int(unit["start"]) >= 0
        ]
        refined.append(item)

    logger.info(
        "Evidence refiner: chunks=%d->%d units=%d->%d chars=%d",
        len(chunks),
        len(refined),
        len(candidates),
        len(admitted),
        used_chars,
    )
    return refined or chunks
