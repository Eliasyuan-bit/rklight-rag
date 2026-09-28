"""Dependency-free BM25 retrieval and weighted RRF for board-local chunks."""
from __future__ import annotations

import asyncio
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
from typing import Any

from lightrag.utils import logger


_TERM_RE = re.compile(r"[A-Za-z0-9]+(?:[._/:+-][A-Za-z0-9]+)*|[\u3400-\u9fff]+")
_IDENTIFIER_SPLIT_RE = re.compile(r"[._/:+-]+")
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[int, list[dict[str, Any]], list[Counter[str]], Counter[str], float]] = {}


def log_chunk_stage(
    query: str,
    stage: str,
    chunks: list[dict[str, Any]],
    *,
    source_type: str = "mixed",
    input_count: int | None = None,
    requested_top_k: int | None = None,
    token_budget: int | None = None,
) -> None:
    """Log compact retrieval decisions without exposing query or chunk text."""
    trace_id = hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]
    records = []
    for rank, chunk in enumerate(chunks, 1):
        record: dict[str, Any] = {
            "rank": rank,
            "chunk_id": str(chunk.get("chunk_id") or chunk.get("id") or ""),
            "file": Path(str(chunk.get("file_path") or "unknown_source")).name,
            "source": chunk.get("source_type", "vector"),
            "chars": len(str(chunk.get("content") or "")),
        }
        for key in ("rrf_score", "lexical_score", "rerank_score"):
            value = chunk.get(key)
            if value is not None:
                try:
                    record[key] = round(float(value), 6)
                except (TypeError, ValueError):
                    record[key] = str(value)
        records.append(record)
    logger.info(
        "Retrieval trace: trace_id=%s stage=%s source=%s input=%s output=%d "
        "requested_top_k=%s token_budget=%s chunks=%s",
        trace_id,
        stage,
        source_type,
        input_count if input_count is not None else len(chunks),
        len(chunks),
        requested_top_k,
        token_budget,
        json.dumps(records, ensure_ascii=False, separators=(",", ":")),
    )


def retrieval_candidate_k(requested_top_k: int) -> int:
    configured = int(os.getenv("RK_RETRIEVAL_CANDIDATE_K", "6"))
    return max(requested_top_k, configured)


def _expand_query(query: str) -> str:
    """Append configured domain identifiers for colloquial trigger terms."""
    raw = os.getenv("RK_LEXICAL_QUERY_EXPANSIONS", "").strip()
    if not raw:
        return query
    try:
        expansions = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Ignoring invalid RK_LEXICAL_QUERY_EXPANSIONS JSON")
        return query
    if not isinstance(expansions, dict):
        return query
    folded = query.casefold()
    additions = []
    for trigger, terms in expansions.items():
        if str(trigger).casefold() not in folded:
            continue
        if isinstance(terms, list):
            additions.extend(str(term) for term in terms)
        elif terms:
            additions.append(str(terms))
    return query + (" " + " ".join(additions) if additions else "")


def preserve_focused_evidence(
    merged_chunks: list[dict[str, Any]],
    vector_chunks: list[dict[str, Any]],
) -> int:
    """Restore focused lexical passages lost during mixed round-robin merge.

    Entity or relation retrieval may insert a full copy of a chunk before the
    same chunk is reached in the fused vector list. Deduplication then keeps
    the oversized copy. Replace it by chunk ID with the bounded lexical
    passage so reranking and final token truncation see the intended evidence.
    """
    focused = {
        str(chunk.get("chunk_id") or chunk.get("id")): chunk
        for chunk in vector_chunks
        if chunk.get("lexical_score") is not None
        and (chunk.get("chunk_id") or chunk.get("id"))
    }
    restored = 0
    for chunk in merged_chunks:
        chunk_id = str(chunk.get("chunk_id") or chunk.get("id") or "")
        preferred = focused.get(chunk_id)
        if not preferred:
            continue
        if chunk.get("content") != preferred.get("content"):
            restored += 1
        chunk["content"] = preferred.get("content", chunk.get("content", ""))
        chunk["file_path"] = preferred.get(
            "file_path", chunk.get("file_path", "unknown_source")
        )
        chunk["source_type"] = "lexical-fused"
        for key in ("rrf_score", "lexical_score"):
            if preferred.get(key) is not None:
                chunk[key] = preferred[key]
    return restored


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _TERM_RE.finditer(text.casefold()):
        term = match.group(0)
        if "\u3400" <= term[0] <= "\u9fff":
            tokens.extend(term)
            tokens.extend(term[i : i + 2] for i in range(len(term) - 1))
        else:
            tokens.append(term)
            parts = [part for part in _IDENTIFIER_SPLIT_RE.split(term) if part]
            if len(parts) > 1:
                tokens.extend(parts)
    return tokens


def _load_index(path: Path):
    stat = path.stat()
    cache_key = str(path)
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and cached[0] == stat.st_mtime_ns:
            return cached[1:]

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"lexical chunk store must be an object: {path}")
    documents = []
    term_counts = []
    document_frequency: Counter[str] = Counter()
    total_length = 0
    for chunk_id, value in raw.items():
        if not isinstance(value, dict) or not value.get("content"):
            continue
        document = dict(value)
        document["chunk_id"] = chunk_id
        document["source_type"] = "lexical"
        counts = Counter(_tokens(str(document["content"])))
        documents.append(document)
        term_counts.append(counts)
        document_frequency.update(counts.keys())
        total_length += sum(counts.values())
    average_length = total_length / len(documents) if documents else 0.0
    result = (documents, term_counts, document_frequency, average_length)
    with _CACHE_LOCK:
        _CACHE[cache_key] = (stat.st_mtime_ns, *result)
    return result


def _bm25(query: str, path: Path, top_k: int) -> list[dict[str, Any]]:
    documents, term_counts, document_frequency, average_length = _load_index(path)
    expanded_query = _expand_query(query)
    query_terms = Counter(_tokens(expanded_query))
    if not query_terms or not documents:
        return []
    count = len(documents)
    k1 = 1.5
    b = 0.75
    ranked = []
    exact_terms = {
        term for term in _TERM_RE.findall(expanded_query.casefold())
        if len(term) >= 3 and (not term.isalpha() or term.isascii())
    }
    for document, counts in zip(documents, term_counts):
        length = sum(counts.values())
        score = 0.0
        for term, query_frequency in query_terms.items():
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            df = document_frequency[term]
            inverse_document_frequency = math.log(1.0 + (count - df + 0.5) / (df + 0.5))
            denominator = frequency + k1 * (
                1.0 - b + b * length / max(average_length, 1.0)
            )
            score += query_frequency * inverse_document_frequency * frequency * (k1 + 1.0) / denominator
        content_folded = str(document["content"]).casefold()
        exact_hits = sum(1 for term in exact_terms if term in content_folded)
        score += exact_hits * float(os.getenv("RK_LEXICAL_EXACT_BOOST", "2.0"))
        if score > 0:
            ranked.append((score, document))
    ranked.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
    return [
        {
            **document,
            "content": _best_passage(str(document["content"]), expanded_query),
            "lexical_score": score,
        }
        for score, document in ranked[:top_k]
    ]


def _passage_tokens(text: str) -> list[str]:
    """Tokenize evidence lines without splitting composite identifiers."""
    tokens: list[str] = []
    for match in _TERM_RE.finditer(text.casefold()):
        term = match.group(0)
        if "\u3400" <= term[0] <= "\u9fff":
            tokens.extend(term[index : index + 2] for index in range(len(term) - 1))
        else:
            tokens.append(term)
    return tokens


def _line_score(line: str, query_tokens: Counter[str]) -> float:
    counts = Counter(_tokens(line))
    return sum(min(counts.get(term, 0), frequency) for term, frequency in query_tokens.items())


def _passage_line_score(line: str, query_tokens: Counter[str]) -> float:
    counts = Counter(_passage_tokens(line))
    return sum(min(counts.get(term, 0), frequency) for term, frequency in query_tokens.items())


def _passage_query_tokens(query: str) -> Counter[str]:
    """Use Chinese bigrams and intact identifiers for focused passages."""
    return Counter(_passage_tokens(query))


def _metric_table_passage(lines: list[str], query: str, max_chars: int) -> str | None:
    """Keep a metric table's header and matching rows in one clean passage."""
    folded_query = query.casefold()
    if not any(term in folded_query for term in ("性能", "performance", "ttft", "tpot", "tps", "吞吐", "延迟")):
        return None
    identifiers = [
        token
        for token in re.findall(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+", folded_query)
        if any(char.isdigit() for char in token)
    ]
    if not identifiers:
        return None
    folded_lines = [line.casefold() for line in lines]
    matching = [
        index
        for index, line in enumerate(folded_lines)
        if any(identifier in line for identifier in identifiers)
    ]
    if not matching:
        return None
    header_index = None
    for index in range(matching[0], -1, -1):
        compact = re.sub(r"\s+", "", folded_lines[index])
        if "llmmodelperformance" in compact or "modelperformance" in compact:
            header_index = index
            break
    if header_index is None:
        return None
    header_block = "".join(lines[header_index : matching[0]])
    compact_header = re.sub(r"\s+", "", header_block.casefold())
    header_hits = sum(
        term in compact_header
        for term in ("modelname", "accelerator", "ttft", "tpot", "decodetps")
    )
    if header_hits < 3:
        return None
    end = matching[-1] + 1
    passage = "".join(lines[header_index:end]).strip()
    return passage[:max_chars] if passage else None


def _markdown_headings(lines: list[str]) -> list[tuple[int, int, set[str]]]:
    """Return Markdown headings while ignoring hash comments inside code fences."""
    headings: list[tuple[int, int, set[str]]] = []
    fence: str | None = None
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        fence_match = re.match(r"^(```+|~~~+)", stripped)
        if fence_match:
            marker = fence_match.group(1)[0]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is not None:
            continue
        match = re.match(r"^(#{1,6})\s+", stripped)
        if match:
            headings.append((index, len(match.group(1)), set(_tokens(stripped))))
    return headings


def _multi_section_passage(lines: list[str], query: str, max_chars: int) -> str | None:
    """Collect several named Markdown sections for comparison-style queries."""
    query_terms = []
    for term in _TERM_RE.findall(query.casefold()):
        if term.isascii() and len(term) >= 2 and term not in query_terms:
            query_terms.append(term)

    headings = _markdown_headings(lines)

    selected: list[tuple[int, int]] = []
    selected_indices: set[int] = set()
    for term in query_terms:
        for index, level, tokens in headings:
            if term in tokens and index not in selected_indices:
                selected.append((index, level))
                selected_indices.add(index)
                break
    if len(selected) < 2:
        return None

    selected.sort()
    separator = "\n\n"
    available = max_chars - len(separator) * (len(selected) - 1)
    quota = max(160, available // len(selected))
    query_tokens = _passage_query_tokens(query)
    excerpts = []
    for start, level in selected:
        end = len(lines)
        for index, next_level, _ in headings:
            if index > start and next_level <= level:
                end = index
                break
        section_lines = lines[start:end]
        heading = section_lines[0].strip()
        section_query_tokens = query_tokens.copy()
        # The heading already establishes object ownership.  Do not let the
        # object name alone select every body line that repeats it; body lines
        # must match the comparison dimensions or their expanded identifiers.
        for heading_term in set(_tokens(heading)):
            section_query_tokens.pop(heading_term, None)
        candidates = [
            (index, _passage_line_score(line, section_query_tokens), line.strip())
            for index, line in enumerate(section_lines[1:], 1)
            if line.strip()
        ]
        matching = [item for item in candidates if item[1] > 0]
        matching.sort(key=lambda item: (-item[1], item[0]))
        chosen: dict[int, str] = {}
        used = len(heading)
        for index, _, line in matching:
            if used + 1 + len(line) > quota:
                continue
            chosen[index] = line
            used += 1 + len(line)
        # Comparison prompts need a clean object-to-fact mapping.  Once a
        # section has direct matches, unrelated setup/tail lines only make a
        # small model more likely to copy a fact into the neighbouring object.
        # Keep leading context solely as a fallback for a named section that
        # otherwise has no matching facts.
        if not chosen:
            for index, _, line in candidates:
                if used + 1 + len(line) > quota:
                    continue
                chosen[index] = line
                used += 1 + len(line)
        excerpt = "\n".join([heading] + [chosen[index] for index in sorted(chosen)])
        excerpts.append(excerpt)
    passage = separator.join(excerpt for excerpt in excerpts if excerpt)
    return passage[:max_chars] or None


def _best_passage(content: str, query: str) -> str:
    """Return a bounded, line-aligned window around the strongest lexical hit."""
    max_chars = max(512, int(os.getenv("RK_LEXICAL_PASSAGE_CHARS", "2400")))
    lines = content.splitlines(keepends=True)
    metric_table = _metric_table_passage(lines, query, max_chars)
    if metric_table:
        return metric_table
    multi_section = _multi_section_passage(lines, query, max_chars)
    if multi_section:
        return multi_section
    if len(content) <= max_chars:
        return content
    query_tokens = _passage_query_tokens(query)
    scores = [_line_score(line, query_tokens) for line in lines]
    best = max(range(len(lines)), key=lambda index: (scores[index], -index))
    start = best
    end = best + 1
    used = len(lines[best])
    # Include the nearest Markdown heading to retain the evidence's section.
    heading = ""
    lower_bound = 0
    valid_heading_indices = {index for index, _, _ in _markdown_headings(lines)}
    for index in range(best, -1, -1):
        if index in valid_heading_indices:
            heading_span = sum(len(line) for line in lines[index:end])
            if heading_span <= max_chars:
                heading = lines[index].strip()
                start = index
                lower_bound = index
                used = heading_span
            break
    while True:
        changed = False
        # Evidence normally follows its Markdown heading, so grow forward
        # first; then add preceding context without starving the matched body.
        if end < len(lines) and used + len(lines[end]) <= max_chars:
            used += len(lines[end])
            end += 1
            changed = True
        if start > lower_bound and used + len(lines[start - 1]) <= max_chars:
            used += len(lines[start - 1])
            start -= 1
            changed = True
        if not changed:
            break
    passage = "".join(lines[start:end]).strip()
    return passage[:max_chars]


async def fuse_vector_and_lexical_chunks(
    query: str,
    vector_chunks: list[dict[str, Any]],
    global_config: dict[str, Any],
    requested_top_k: int,
) -> list[dict[str, Any]]:
    """Fuse vector and BM25 ranks while retaining candidates for reranking."""
    working_dir = global_config.get("working_dir") or global_config.get("WORKING_DIR")
    if not working_dir or os.getenv("RK_LEXICAL_RETRIEVAL", "true").lower() != "true":
        return vector_chunks
    store_path = Path(working_dir) / "kv_store_text_chunks.json"
    if not store_path.is_file():
        logger.warning("Lexical retrieval disabled: chunk store not found at %s", store_path)
        return vector_chunks

    candidate_k = retrieval_candidate_k(requested_top_k)
    lexical_chunks = await asyncio.to_thread(_bm25, query, store_path, candidate_k)
    rrf_k = float(os.getenv("RK_RRF_K", "60"))
    vector_weight = float(os.getenv("RK_RRF_VECTOR_WEIGHT", "1.0"))
    lexical_weight = float(os.getenv("RK_RRF_LEXICAL_WEIGHT", "1.5"))
    fused: dict[str, dict[str, Any]] = {}
    scores: Counter[str] = Counter()
    for rank, chunk in enumerate(vector_chunks, 1):
        chunk_id = str(chunk.get("chunk_id") or chunk.get("id") or "")
        if not chunk_id:
            continue
        fused[chunk_id] = dict(chunk)
        scores[chunk_id] += vector_weight / (rrf_k + rank)
    for rank, chunk in enumerate(lexical_chunks, 1):
        chunk_id = str(chunk["chunk_id"])
        if chunk_id not in fused:
            fused[chunk_id] = {
                "content": chunk["content"],
                "created_at": chunk.get("created_at", chunk.get("create_time")),
                "file_path": chunk.get("file_path", "unknown_source"),
                "source_type": "lexical",
                "chunk_id": chunk_id,
            }
        else:
            # The vector record contains the full ingestion chunk. Use the
            # bounded lexical passage for reranking and generation so a large
            # P! chunk cannot consume the complete evidence budget.
            fused[chunk_id]["content"] = chunk["content"]
        fused[chunk_id]["lexical_score"] = chunk.get("lexical_score")
        scores[chunk_id] += lexical_weight / (rrf_k + rank)
    ranked_ids = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:candidate_k]
    result = [{**fused[chunk_id], "rrf_score": scores[chunk_id]} for chunk_id in ranked_ids]
    logger.info(
        "Chunk retrieval fusion: vector=%d lexical=%d fused=%d requested_top_k=%d candidate_k=%d",
        len(vector_chunks), len(lexical_chunks), len(result), requested_top_k, candidate_k,
    )
    log_chunk_stage(
        query,
        "fused",
        result,
        source_type="vector+lexical",
        input_count=len(vector_chunks) + len(lexical_chunks),
        requested_top_k=requested_top_k,
    )
    return result
