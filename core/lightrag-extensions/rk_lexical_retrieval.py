"""Dependency-free BM25 retrieval and weighted RRF for board-local chunks."""
from __future__ import annotations

import asyncio
from collections import Counter
import hashlib
import html
import json
import logging
import math
import os
from pathlib import Path
import re
import threading
from typing import Any

_TERM_RE = re.compile(r"[A-Za-z0-9]+(?:[._/:+-][A-Za-z0-9]+)*|[\u3400-\u9fff]+")
_IDENTIFIER_SPLIT_RE = re.compile(r"[._/:+-]+")
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[int, list[dict[str, Any]], list[Counter[str]], Counter[str], float]] = {}
logger = logging.getLogger("lightrag")

_EXACT_QUERY_INTENTS = (
    "版本",
    "命令",
    "参数",
    "输出",
    "路径",
    "错误码",
    "日志",
    "型号",
    "地址",
    "version",
    "command",
    "parameter",
    "output",
    "path",
    "error code",
)
_SEMANTIC_QUERY_INTENTS = (
    "介绍",
    "概述",
    "原理",
    "总结",
    "是什么",
    "说明一下",
    "overview",
    "explain",
    "summarize",
)
_TABLE_QUERY_INTENTS = (
    "性能", "规格", "参数", "吞吐", "精度", "量化", "对比表", "ttft", "tpot", "decode", "tps",
)
_DOCUMENT_FACT_QUERY_INTENTS = (
    "配置流程",
    "如何配置",
    "怎么配置",
    "支持哪些",
    "有哪些",
    "哪些模式",
    "哪些策略",
    "哪些 strategy",
    "which modes",
    "what modes",
    "which strategies",
    "what strategies",
    "how to configure",
)
_COMPOSITE_IDENTIFIER_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9]*(?:[._/:+-][A-Za-z0-9]+)+"
)
_VERSION_RE = re.compile(r"(?i)\bv?\d+(?:\.\d+){1,}(?:[_-][A-Za-z0-9]+)*\b")
_CLI_FLAG_RE = re.compile(r"(?<![\w-])--?[A-Za-z][A-Za-z0-9-]*\b")
_HEX_RE = re.compile(r"(?i)\b0x[0-9a-f]+\b")
_NAMED_DIGIT_RE = re.compile(r"(?i)\b[A-Za-z][A-Za-z0-9_.+-]*\d[A-Za-z0-9_.+-]*\b")
_SPACED_IDENTIFIER_RE = re.compile(
    r"\b[A-Za-z][A-Za-z0-9]*(?:\s*(?:[._/:+-]\s*|\s+)\d+(?:\s*(?:[._/:+-]\s*|\s+)[A-Za-z0-9]+)*)"
)
_NAMED_PHRASE_RE = re.compile(
    r"\b[A-Za-z][A-Za-z0-9]*(?:\s+[A-Za-z][A-Za-z0-9]*)+\b"
)
_RELATION_ASSIGNMENT_MARKERS = ("设置为", "设为", "指向", "转给", "流向")


def _compact_identifier(value: str) -> str:
    """Canonical retrieval key for a technical identifier, never for display."""
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _index_text(content: str, table_type: str = "") -> str:
    """Build a generic retrieval-only normalization view of source text.

    PDF extraction can insert spaces around *any* technical identifier, such
    as ``Qwen 2.5 7B``, ``RKNN 3 SDK`` or ``DDR 4``. Every identifier with a
    number receives a punctuation/space-insensitive key. The original source
    text is never changed or sent to the generator differently.
    """
    aliases = {
        _compact_identifier(match.group(0))
        for match in _SPACED_IDENTIFIER_RE.finditer(content)
        if any(character.isdigit() for character in match.group(0))
    }
    type_terms = {
        "server_config": "server configuration recommended conversion time 服务器 配置 推荐 转换 时间",
        "accuracy": "accuracy precision float32 w4a16 精度 准确率",
        "llm_performance": "llm model performance ttft tpot decode tps 性能",
        "vlm_performance": "vlm vision model performance visual 性能 视觉",
    }.get(table_type, "")
    return "\n".join(part for part in (content, " ".join(sorted(aliases)), type_terms) if part)


def query_retrieval_profile(query: str) -> str:
    """Classify only the retrieval signal needed for soft hybrid weighting.

    Both sparse and dense retrieval always run.  This profile changes their
    contribution; it is not a hard router and does not encode domain answers.
    """
    folded = query.casefold()
    # Technical metric/model questions need a row-aware sparse signal. This
    # remains a soft profile: vector retrieval and reranking still run.
    if any(term in folded for term in _TABLE_QUERY_INTENTS):
        return "table"
    # An explicit assignment/flow relation takes precedence over an
    # enumeration suffix.  For example, "A points to B; which strategies ..."
    # is a compound relation question, while "which strategies does B support"
    # is an ordinary document fact.  Checking the relation first preserves the
    # graph path for genuine two-hop questions without sending simple lists to
    # the graph.
    if relation_evidence_anchors(query):
        return "relation_fact"
    # Configuration procedures and simple enumerations are normally answered
    # by a contiguous source passage.
    if any(term in folded for term in _DOCUMENT_FACT_QUERY_INTENTS):
        return "document_fact"
    has_exact_intent = any(term in folded for term in _EXACT_QUERY_INTENTS)
    has_exact_shape = any(
        pattern.search(query)
        for pattern in (
            _COMPOSITE_IDENTIFIER_RE,
            _VERSION_RE,
            _CLI_FLAG_RE,
            _HEX_RE,
            _NAMED_DIGIT_RE,
        )
    )
    if has_exact_shape and has_exact_intent:
        return "exact"
    if has_exact_shape and len(query.strip()) <= 48:
        return "exact"
    if any(term in folded for term in _SEMANTIC_QUERY_INTENTS):
        return "semantic"
    return "balanced"


def _named_phrases(value: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", match.group(0)).strip().casefold()
        for match in _NAMED_PHRASE_RE.finditer(value)
    ]


def _query_expansion_terms(query: str) -> list[str]:
    """Return configured aliases whose trigger is present in *query*."""
    raw = os.getenv("RK_LEXICAL_QUERY_EXPANSIONS", "").strip()
    if not raw:
        return []
    try:
        expansions = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Ignoring invalid RK_LEXICAL_QUERY_EXPANSIONS JSON")
        return []
    if not isinstance(expansions, dict):
        return []
    folded = query.casefold()
    additions: list[str] = []
    for trigger, terms in expansions.items():
        if str(trigger).casefold() not in folded:
            continue
        if isinstance(terms, list):
            additions.extend(str(term) for term in terms)
        elif terms:
            additions.append(str(terms))
    return additions


def relation_evidence_anchors(query: str) -> tuple[str, ...]:
    """Extract the two operands of a direct relationship assertion.

    This is syntax-based rather than domain-specific. For a query such as
    ``set A to B`` it identifies the closest named phrase on each side.
    Configured cross-language expansions may supply an English phrase for a
    Chinese operand so both operands can be matched in an English passage.
    """
    for marker in _RELATION_ASSIGNMENT_MARKERS:
        if marker not in query:
            continue
        left, right = query.split(marker, 1)
        left_phrases = _named_phrases(left)
        right_phrases = _named_phrases(right)
        if not left_phrases:
            left_phrases = [
                phrase
                for term in _query_expansion_terms(left)
                for phrase in _named_phrases(term)
            ]
        if not right_phrases:
            right_phrases = [
                phrase
                for term in _query_expansion_terms(right)
                for phrase in _named_phrases(term)
            ]
        if not left_phrases or not right_phrases:
            continue
        anchors = (left_phrases[-1], right_phrases[0])
        if anchors[0] != anchors[1]:
            return anchors
    return ()


def relation_evidence_coverage(
    query: str, content: str
) -> tuple[int, int, tuple[str, ...]]:
    anchors = relation_evidence_anchors(query)
    if not anchors:
        return 0, 0, ()
    folded = re.sub(r"\s+", " ", content).casefold()
    matched = tuple(anchor for anchor in anchors if anchor in folded)
    return len(matched), len(anchors), matched


def relation_evidence_span(query: str, content: str) -> int | None:
    """Return the tightest character span joining both relation operands."""
    anchors = relation_evidence_anchors(query)
    if len(anchors) != 2:
        return None
    folded = re.sub(r"\s+", " ", content).casefold()
    positions: list[list[int]] = []
    for anchor in anchors:
        found: list[int] = []
        start = 0
        while True:
            index = folded.find(anchor, start)
            if index < 0:
                break
            found.append(index)
            start = index + 1
        if not found:
            return None
        positions.append(found)
    return min(abs(left - right) for left in positions[0] for right in positions[1])


def _is_direct_relation_evidence(query: str, content: str) -> bool:
    matched, total, _ = relation_evidence_coverage(query, content)
    span = relation_evidence_span(query, content)
    maximum_span = max(1, int(os.getenv("RK_RELATION_FACT_MAX_SPAN_CHARS", "480")))
    return matched == total and total >= 2 and span is not None and span <= maximum_span


def query_direct_identifiers(query: str) -> tuple[str, ...]:
    """Return literal identifiers that a direct evidence passage should carry.

    This deliberately ignores ordinary natural-language terms.  It covers
    model names, commands, flags, versions and hexadecimal values, which are
    the kinds of facts semantic similarity can blur without proving that the
    requested object is present in the evidence.
    """
    identifiers = set(_COMPOSITE_IDENTIFIER_RE.findall(query.casefold()))
    identifiers.update(_VERSION_RE.findall(query.casefold()))
    identifiers.update(_CLI_FLAG_RE.findall(query.casefold()))
    identifiers.update(_HEX_RE.findall(query.casefold()))
    identifiers.update(
        token.casefold()
        for token in _TERM_RE.findall(query)
        if len(token) >= 3
        and token.isascii()
        and ("_" in token or any(char.isdigit() for char in token))
    )
    return tuple(sorted(identifiers, key=lambda item: (-len(item), item)))


def direct_evidence_coverage(query: str, content: str) -> tuple[int, int, tuple[str, ...]]:
    """Measure literal query-identifier coverage in a candidate passage."""
    identifiers = query_direct_identifiers(query)
    if not identifiers:
        return 0, 0, ()
    folded = content.casefold()
    matched = tuple(identifier for identifier in identifiers if identifier in folded)
    return len(matched), len(identifiers), matched


def query_aware_rrf_weights(query: str) -> tuple[str, float, float]:
    profile = query_retrieval_profile(query)
    if profile == "table":
        return (
            profile,
            float(os.getenv("RK_RRF_TABLE_VECTOR_WEIGHT", "0.85")),
            float(os.getenv("RK_RRF_TABLE_LEXICAL_WEIGHT", "2.75")),
        )
    if profile == "exact":
        return (
            profile,
            float(os.getenv("RK_RRF_EXACT_VECTOR_WEIGHT", "0.75")),
            float(os.getenv("RK_RRF_EXACT_LEXICAL_WEIGHT", "2.5")),
        )
    if profile == "semantic":
        return (
            profile,
            float(os.getenv("RK_RRF_SEMANTIC_VECTOR_WEIGHT", "1.5")),
            float(os.getenv("RK_RRF_SEMANTIC_LEXICAL_WEIGHT", "1.0")),
        )
    if profile == "document_fact":
        return (
            profile,
            float(os.getenv("RK_RRF_DOCUMENT_FACT_VECTOR_WEIGHT", "1.5")),
            float(os.getenv("RK_RRF_DOCUMENT_FACT_LEXICAL_WEIGHT", "1.5")),
        )
    if profile == "relation_fact":
        return (
            profile,
            float(os.getenv("RK_RRF_RELATION_FACT_VECTOR_WEIGHT", "1.0")),
            float(os.getenv("RK_RRF_RELATION_FACT_LEXICAL_WEIGHT", "1.75")),
        )
    return (
        profile,
        float(os.getenv("RK_RRF_VECTOR_WEIGHT", "1.0")),
        float(os.getenv("RK_RRF_LEXICAL_WEIGHT", "1.5")),
    )


def query_aware_rerank_top_n(
    query: str, chunks: list[dict[str, Any]], requested_top_k: int
) -> int:
    """Expose enough exact-query candidates for post-rerank fusion."""
    if query_retrieval_profile(query) not in (
        "exact", "table", "document_fact", "relation_fact"
    ):
        return requested_top_k
    maximum = max(requested_top_k, int(os.getenv("RK_EXACT_RERANK_CANDIDATE_K", "12")))
    return min(len(chunks), maximum)


def fuse_query_aware_rerank(
    query: str,
    reranked_chunks: list[dict[str, Any]],
    requested_top_k: int,
) -> list[dict[str, Any]]:
    """Blend rerank and retrieval ranks while reserving direct lexical evidence.

    The reranker remains authoritative for normal semantic queries.  Exact
    queries additionally retain the best substantive BM25 passage so a
    command, version, path, or error code cannot disappear after recall.
    """
    profile = query_retrieval_profile(query)
    if profile not in (
        "exact", "table", "document_fact", "relation_fact"
    ) or not reranked_chunks:
        return reranked_chunks

    rrf_k = float(os.getenv("RK_POST_RERANK_RRF_K", "60"))
    rerank_weight = float(os.getenv("RK_POST_RERANK_WEIGHT", "1.0"))
    retrieval_weight = float(os.getenv("RK_POST_RERANK_RETRIEVAL_WEIGHT", "0.7"))
    lexical_weight = float(os.getenv("RK_POST_RERANK_LEXICAL_WEIGHT", "1.5"))
    ordered = []
    for rerank_rank, chunk in enumerate(reranked_chunks, 1):
        item = chunk.copy()
        retrieval_rank = int(item.get("retrieval_rank") or rerank_rank)
        lexical_rank = item.get("lexical_rank")
        score = rerank_weight / (rrf_k + rerank_rank)
        score += retrieval_weight / (rrf_k + retrieval_rank)
        if lexical_rank is not None:
            score += lexical_weight / (rrf_k + int(lexical_rank))
        item["query_aware_score"] = score
        ordered.append(item)
    ordered.sort(
        key=lambda item: (
            -float(item["query_aware_score"]),
            int(item.get("retrieval_rank") or 10**9),
        )
    )

    limit = max(1, requested_top_k)
    selected = ordered[:limit]
    direct_candidates = []
    for item in ordered:
        evidence_source = str(
            item.get("full_content") or item.get("content") or ""
        )
        matched, total, identifiers = direct_evidence_coverage(
            query, evidence_source
        )
        if matched and _has_substantive_evidence(evidence_source):
            item["exact_evidence_coverage"] = matched
            item["exact_evidence_identifier_count"] = total
            item["exact_evidence_identifiers"] = list(identifiers)
            direct_candidates.append(item)
    if profile == "document_fact":
        # For procedural/enumeration questions the fused text rank is more
        # reliable than the highest standalone BM25 rank. Generic words such
        # as "configuration" can otherwise protect an unrelated document.
        protected = next(
            (
                item
                for item in sorted(
                    ordered,
                    key=lambda value: int(value.get("retrieval_rank") or 10**9),
                )
                if _has_substantive_evidence(str(item.get("content") or ""))
            ),
            None,
        )
    elif profile == "relation_fact":
        relation_candidates = []
        for item in ordered:
            evidence_source = str(
                item.get("full_content") or item.get("content") or ""
            )
            matched, total, anchors = relation_evidence_coverage(
                query, evidence_source
            )
            if _is_direct_relation_evidence(
                query, evidence_source
            ) and _has_substantive_evidence(evidence_source):
                item["relation_evidence_coverage"] = matched
                item["relation_evidence_anchor_count"] = total
                item["relation_evidence_anchors"] = list(anchors)
                relation_candidates.append(item)
        protected = (
            min(
                relation_candidates,
                key=lambda value: (
                    int(value.get("lexical_rank") or 10**9),
                    int(value.get("retrieval_rank") or 10**9),
                ),
            )
            if relation_candidates
            else None
        )
    else:
        protected = (
            min(
                direct_candidates,
                key=lambda value: (
                    -int(value["exact_evidence_coverage"]),
                    -int(value["exact_evidence_identifier_count"]),
                    int(value.get("lexical_rank") or 10**9),
                    int(value.get("retrieval_rank") or 10**9),
                ),
            )
            if direct_candidates
            else next(
            (
                item
                for item in sorted(
                    ordered,
                    key=lambda value: int(value.get("lexical_rank") or 10**9),
                )
                if item.get("lexical_rank") is not None
                and _has_substantive_evidence(str(item.get("content") or ""))
            ),
            None,
            )
        )
    if protected is not None:
        protected_id = str(protected.get("chunk_id") or protected.get("id") or "")
        if all(
            str(item.get("chunk_id") or item.get("id") or "") != protected_id
            for item in selected
        ):
            selected[-1] = protected
        for item in selected:
            if str(item.get("chunk_id") or item.get("id") or "") == protected_id:
                item["exact_retrieval_protected"] = True
                break
    selected.sort(key=lambda item: -float(item["query_aware_score"]))
    logger.info(
        "Query-aware rerank fusion: profile=%s input=%d output=%d protected=%s",
        profile,
        len(reranked_chunks),
        len(selected),
        protected_id if protected is not None else "none",
    )
    return selected


def _has_substantive_evidence(content: str) -> bool:
    body = re.sub(r"(?m)^\s*#{1,6}\s+.*$", "", content)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip()
    return len(body) >= int(os.getenv("RK_EXACT_MIN_EVIDENCE_CHARS", "24"))


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


def retrieval_candidate_k(requested_top_k: int, query: str = "") -> int:
    configured = int(os.getenv("RK_RETRIEVAL_CANDIDATE_K", "6"))
    if query and query_retrieval_profile(query) in (
        "exact", "table", "document_fact"
    ):
        configured = max(
            configured,
            int(os.getenv("RK_EXACT_RETRIEVAL_CANDIDATE_K", "12")),
        )
    return max(requested_top_k, configured)


def _expand_query(query: str) -> str:
    """Append configured domain identifiers for colloquial trigger terms."""
    additions = _query_expansion_terms(query)
    return query + (" " + " ".join(additions) if additions else "")


def bound_mix_graph_chunks(
    entity_chunks: list[dict[str, Any]],
    relation_chunks: list[dict[str, Any]],
    query_param: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Bound graph-derived chunk fan-out before mixed-mode neural reranking.

    LightRAG scales the number of related chunks with the number of matched
    entities and relations.  On a large manual, even a one-hop question can
    therefore turn six text candidates into dozens of reranker inputs.  Mix
    still keeps graph evidence, but admits only a small, independently
    configurable prefix from each graph source.
    """
    if getattr(query_param, "mode", None) != "mix":
        return entity_chunks, relation_chunks

    entity_cap = max(0, int(os.getenv("RK_MIX_ENTITY_CHUNK_CAP", "6")))
    relation_cap = max(0, int(os.getenv("RK_MIX_RELATION_CHUNK_CAP", "6")))
    return entity_chunks[:entity_cap], relation_chunks[:relation_cap]


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
        for key in (
            "rrf_score",
            "lexical_score",
            "vector_rank",
            "lexical_rank",
            "retrieval_rank",
            "retrieval_profile",
            "relation_evidence_candidate",
            "relation_evidence_anchors",
        ):
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
            if any(character.isdigit() for character in term):
                compact = _compact_identifier(term)
                if compact and compact != term:
                    tokens.append(compact)
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
        document["search_content"] = _index_text(str(document["content"]))
        counts = Counter(_tokens(document["search_content"]))
        documents.append(document)
        term_counts.append(counts)
        document_frequency.update(counts.keys())
        total_length += sum(counts.values())
    # Optional persistent PDF table parents.  They are separate lexical
    # documents so a row can be recalled even when its original prose chunk
    # is not in the vector candidate window.
    parent_path = Path(os.getenv("RK_TABLE_PARENT_INDEX", str(path.with_name("table_parent_index.json"))))
    if parent_path.exists():
        try:
            parent_raw = json.loads(parent_path.read_text(encoding="utf-8"))
            parent_tables = parent_raw.get("tables", []) if isinstance(parent_raw, dict) else []
        except (OSError, json.JSONDecodeError):
            parent_tables = []
        for table in parent_tables:
            if not isinstance(table, dict) or not table.get("parent_content"):
                continue
            table_id = str(table.get("table_id") or "")
            if not table_id:
                continue
            document = {
                "chunk_id": table_id,
                # Keep retrieval IDs unique per table, but retain a real
                # LightRAG chunk for citation preview and document links.
                "reference_chunk_id": table.get("source_chunk_id", ""),
                "source_chunk_id": table.get("source_chunk_id", ""),
                "content": str(table["parent_content"]),
                "full_content": str(table["parent_content"]),
                "file_path": table.get("source_file", ""),
                "table_id": table_id,
                "table_type": table.get("table_type", "unknown"),
                "table_parent": True,
                "source_type": "table-parent",
                "table_headers": table.get("headers", []),
                "table_rows": table.get("rows", []),
                "row_records": table.get("row_records", []),
                "source_chunk_order": table.get("source_chunk_order"),
            }
            document["search_content"] = _index_text(
                document["content"], str(document["table_type"])
            )
            counts = Counter(_tokens(document["search_content"]))
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
        content_folded = str(document.get("search_content") or document["content"]).casefold()
        exact_hits = sum(1 for term in exact_terms if term in content_folded)
        score += exact_hits * float(os.getenv("RK_LEXICAL_EXACT_BOOST", "2.0"))
        if score > 0:
            ranked.append((score, document))
    ranked.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
    result = []
    exact_query = query_retrieval_profile(query) == "exact"
    identifiers = query_direct_identifiers(query)
    for score, document in ranked[:top_k]:
        original = str(document["content"])
        passage = _best_passage(original, expanded_query)
        # A focused window is useful for ordinary prose, but it must not hide
        # the very identifier that made an exact candidate relevant. Keep the
        # complete source available for table packaging and exact protection.
        if exact_query and identifiers and not all(
            identifier in passage.casefold() for identifier in identifiers
        ):
            passage = original[: max(6000, int(os.getenv("RK_EXACT_SOURCE_CHARS", "6000")))]
        result.append(
            {
                **document,
                "content": passage,
                "full_content": original,
                "lexical_score": score,
            }
        )
    return result


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
    html_table = _html_table_passage(content, query, max_chars)
    if html_table:
        return html_table
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


def _html_table_passage(content: str, query: str, max_chars: int) -> str | None:
    """Compact a single-line HTML table without losing its preceding steps."""
    match = re.search(r"<table\b[^>]*>(.*?)</table>", content, re.I | re.S)
    if not match:
        return None
    prefix = content[: match.start()].strip()
    prefix_limit = min(max_chars // 3, 480)
    if len(prefix) > prefix_limit:
        prefix = prefix[-prefix_limit:]
    rows: list[tuple[int, int, str]] = []
    query_tokens = _passage_query_tokens(query)
    for index, row_match in enumerate(
        re.finditer(r"<tr\b[^>]*>(.*?)</tr>", match.group(1), re.I | re.S)
    ):
        cells = []
        for cell_match in re.finditer(
            r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row_match.group(1), re.I | re.S
        ):
            value = re.sub(r"<[^>]+>", " ", cell_match.group(1))
            value = html.unescape(re.sub(r"\s+", " ", value)).strip()
            if value:
                cells.append(value)
        if not cells:
            continue
        rendered = " | ".join(cells)
        rows.append((index, _line_score(rendered, query_tokens), rendered))
    matching = [row for row in rows if row[1] > 0]
    if not matching:
        return None
    matching.sort(key=lambda row: (-row[1], row[0]))
    chosen: dict[int, str] = {}
    used = len(prefix) + len("\n\nTable:\n")
    for index, _, rendered in matching:
        if used + len(rendered) + 1 > max_chars:
            continue
        chosen[index] = rendered
        used += len(rendered) + 1
    if not chosen:
        return None
    parts = [prefix] if prefix else []
    parts.append("Table:\n" + "\n".join(chosen[index] for index in sorted(chosen)))
    return "\n\n".join(parts)[:max_chars]


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

    candidate_k = retrieval_candidate_k(requested_top_k, query)
    profile = query_retrieval_profile(query)
    lexical_scan_k = candidate_k
    if profile == "relation_fact":
        lexical_scan_k = max(
            candidate_k, int(os.getenv("RK_RELATION_FACT_LEXICAL_SCAN_K", "64"))
        )
    lexical_chunks = await asyncio.to_thread(
        _bm25, query, store_path, lexical_scan_k
    )
    rrf_k = float(os.getenv("RK_RRF_K", "60"))
    profile, vector_weight, lexical_weight = query_aware_rrf_weights(query)
    fused: dict[str, dict[str, Any]] = {}
    scores: Counter[str] = Counter()
    for rank, chunk in enumerate(vector_chunks, 1):
        chunk_id = str(chunk.get("chunk_id") or chunk.get("id") or "")
        if not chunk_id:
            continue
        fused[chunk_id] = dict(chunk)
        fused[chunk_id]["vector_rank"] = rank
        scores[chunk_id] += vector_weight / (rrf_k + rank)
    for rank, chunk in enumerate(lexical_chunks, 1):
        chunk_id = str(chunk["chunk_id"])
        if chunk_id not in fused:
            fused[chunk_id] = {
                **chunk,
                "content": chunk["content"],
                "full_content": chunk.get("full_content", chunk["content"]),
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
            fused[chunk_id]["full_content"] = chunk.get(
                "full_content", fused[chunk_id].get("full_content", chunk["content"])
            )
        fused[chunk_id]["lexical_score"] = chunk.get("lexical_score")
        fused[chunk_id]["lexical_rank"] = rank
        scores[chunk_id] += lexical_weight / (rrf_k + rank)
    ranked_ids = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:candidate_k]
    if profile == "relation_fact":
        relation_candidates = []
        for rank, chunk in enumerate(lexical_chunks, 1):
            evidence_source = str(
                chunk.get("full_content") or chunk.get("content") or ""
            )
            matched, total, anchors = relation_evidence_coverage(
                query, evidence_source
            )
            if _is_direct_relation_evidence(query, evidence_source):
                relation_candidates.append((rank, chunk, anchors))
        if relation_candidates:
            _, relation_chunk, anchors = relation_candidates[0]
            protected_id = str(relation_chunk["chunk_id"])
            fused[protected_id]["relation_evidence_candidate"] = True
            fused[protected_id]["relation_evidence_anchors"] = list(anchors)
            if protected_id not in ranked_ids:
                ranked_ids[-1] = protected_id
    result = [
        {
            **fused[chunk_id],
            "rrf_score": scores[chunk_id],
            "retrieval_rank": rank,
            "retrieval_profile": profile,
        }
        for rank, chunk_id in enumerate(ranked_ids, 1)
    ]
    logger.info(
        "Chunk retrieval fusion: profile=%s vector_weight=%.2f lexical_weight=%.2f "
        "vector=%d lexical=%d fused=%d requested_top_k=%d candidate_k=%d",
        profile, vector_weight, lexical_weight, len(vector_chunks),
        len(lexical_chunks), len(result), requested_top_k, candidate_k,
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
