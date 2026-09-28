"""Post-rerank source authority policy for mixed-quality knowledge bases."""
from __future__ import annotations

import os
import json
import re
from typing import Any


_METRIC_QUERY_TERMS = ("性能", "performance", "ttft", "tpot", "tps", "吞吐", "延迟")
_TABLE_HEADER_TERMS = ("modelname", "accelerator", "inputtokens", "newtokens", "ttft", "tpot", "decodetps")
_DIAGNOSTIC_QUERY_TERMS = ("错误", "故障", "失败", "异常", "为什么", "原因")


def _diagnostic_query_identifiers(query: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-z0-9][a-z0-9._+-]*", query.casefold())
        if len(term) >= 2
    }


def _compact_named_sections(query: str, content: str) -> tuple[str | None, int]:
    """Select Markdown sections explicitly named by the user.

    This applies to both diagnostic and explanatory questions. A question such
    as ``介绍一下 USB 测试`` should not expose the neighbouring SET_PN and
    GET_PN sections merely because the parser stored them in one chunk.
    """
    query_terms = _diagnostic_query_identifiers(query)
    if not query_terms:
        return None, 0
    matches = list(re.finditer(r"(?m)^#{1,6}\s+.+$", content))
    if len(matches) < 2:
        return None, 0
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        block = content[match.start() : end].strip()
        heading = match.group(0).casefold()
        score = sum(1 for term in query_terms if term in heading)
        sections.append((score, block))
    best_score = max(score for score, _ in sections)
    if best_score <= 0:
        return None, 0
    selected = [block for score, block in sections if score == best_score]
    if len(selected) == len(sections):
        return None, 0
    return "\n\n".join(selected), best_score


def _compact_named_numbered_item(query: str, content: str) -> tuple[str | None, int]:
    """Select the numbered Markdown item most explicitly named by a query.

    Manuals often put an entire workflow in one chunk even though the user
    names one bold numbered item. Matching multiple ASCII identifiers in the
    item heading is a strong, domain-independent boundary signal and avoids
    asking the answer model to summarize neighbouring workflow steps.
    """
    query_terms = _diagnostic_query_identifiers(query)
    if len(query_terms) < 2:
        return None, 0
    matches = list(re.finditer(r"(?m)^\d+\.\s+\*\*(.+?)\*\*[^\n]*", content))
    if len(matches) < 2:
        return None, 0
    items: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        heading = match.group(1).casefold()
        score = sum(1 for term in query_terms if term in heading)
        items.append((score, content[match.start():end].strip()))
    best_score = max(score for score, _ in items)
    if best_score < 2:
        return None, 0
    selected = [item for score, item in items if score == best_score]
    if len(selected) == len(items):
        return None, 0
    return "\n\n".join(selected), best_score


def _compact_diagnostic_table(query: str, content: str) -> str | None:
    """Keep only table rows addressed by an explicit query identifier.

    Imported manuals sometimes place every error code in one Markdown chunk.
    Reranking can select the right chunk but cannot prevent a small model from
    treating neighbouring rows as additional causes.  When the question names
    an ASCII identifier (for example USB, SARADC or a test code), retain only
    rows containing the strongest identifier match.  Ambiguous/no-match tables
    remain untouched.
    """
    if not any(term in query.casefold() for term in _DIAGNOSTIC_QUERY_TERMS):
        return None
    query_terms = _diagnostic_query_identifiers(query)
    if not query_terms:
        return None
    rows = [
        line
        for line in content.splitlines()
        if line.strip().startswith("|") and line.strip().endswith("|")
    ]
    if len(rows) < 2:
        # Native Markdown parsing stores some tables as a compact JSON matrix
        # inside a <table format="json"> element. Decode those matrices so a
        # matching diagnostic row does not expose neighbouring test items to
        # the small answer model.
        json_rows: list[tuple[str, list[Any]]] = []
        for match in re.finditer(
            r'<table\b[^>]*\bformat=["\']json["\'][^>]*>(.*?)</table>',
            content,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            try:
                matrix = json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(matrix, list):
                continue
            for row in matrix:
                if isinstance(row, list):
                    json_rows.append((json.dumps(row, ensure_ascii=False), row))
        if not json_rows:
            return None
        scored_json = []
        for rendered, row in json_rows:
            folded = rendered.casefold()
            hits = {term for term in query_terms if term in folded}
            scored_json.append((len(hits), row))
        best_score = max(score for score, _ in scored_json)
        if best_score <= 0:
            return None
        selected_json = [row for score, row in scored_json if score == best_score]
        if len(selected_json) == len(json_rows):
            return None
        return '<table format="json">' + json.dumps(
            selected_json, ensure_ascii=False
        ) + "</table>"
    scored = []
    for row in rows:
        folded = row.casefold()
        hits = {term for term in query_terms if term in folded}
        scored.append((len(hits), row))
    best_score = max(score for score, _ in scored)
    if best_score <= 0:
        return None
    selected = [row for score, row in scored if score == best_score]
    # Multiple equally matching rows may represent a split procedure and are
    # safer to retain together; unmatched neighbouring rows are the pollution.
    if len(selected) == len(rows):
        return None
    return "\n".join(selected).strip()


def _query_model_identifiers(query: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+", query.casefold())
        if any(char.isdigit() for char in token)
    ]


def _compact_metric_table(query: str, content: str) -> str | None:
    """Return a table header plus rows for the model family in the query."""
    folded_query = query.casefold()
    if not any(term in folded_query for term in _METRIC_QUERY_TERMS):
        return None
    identifiers = _query_model_identifiers(query)
    if not identifiers:
        return None
    lines = content.splitlines(keepends=True)
    matching = []
    for index, line in enumerate(lines):
        folded_line = line.casefold()
        if not any(identifier in folded_line for identifier in identifiers):
            continue
        # A base-family query such as Qwen2.5 should not be diverted to the
        # Qwen2.5-VL or Qwen2.5-Omni tables.
        if not any(modality in folded_query for modality in ("-vl", "omni")):
            if any(
                f"{identifier}-{modality}" in folded_line
                for identifier in identifiers
                for modality in ("vl", "omni")
            ):
                continue
        matching.append(index)
    if not matching:
        return None
    header_index = None
    for index in range(matching[0], -1, -1):
        compact = re.sub(r"\s+", "", lines[index].casefold())
        if "llmmodelperformance" in compact or compact.endswith("modelperformance"):
            header_index = index
            break
    if header_index is None:
        prefix = re.sub(
            r"\s+", "", "".join(lines[: matching[0]]).casefold()
        )
        if sum(term in prefix for term in _TABLE_HEADER_TERMS) < 3:
            return None
        header_index = 0
    header_block = "".join(lines[header_index : matching[0]]).casefold()
    compact_header = re.sub(r"\s+", "", header_block)
    if sum(term in compact_header for term in _TABLE_HEADER_TERMS) < 3:
        return None
    return "".join(lines[header_index : matching[-1] + 1]).strip()


def _table_evidence_boost(query: str, content: str) -> float:
    """Prefer a matching table block whose header precedes its data row.

    PDF parsing often puts the last row of a table at the start of the next
    chunk.  That row can rerank slightly above the preceding, self-contained
    chunk, but without its header the LLM cannot map values to columns.
    """
    if _compact_metric_table(query, content) is None:
        return 1.0
    return float(os.getenv("RK_TABLE_EVIDENCE_BOOST", "1.5"))


def _source_family(chunk: dict[str, Any]) -> str:
    """Return the upload family shared by raw-text and derived KG routes."""
    source_group_id = str(chunk.get("source_group_id") or "").strip().casefold()
    if source_group_id:
        return source_group_id
    file_path = str(chunk.get("file_path") or "").casefold()
    return re.sub(r"\.(?:kg|text)(?=\.md$)", "", file_path)


def _filter_diagnostic_evidence(
    ranked: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """Keep direct diagnostic evidence and discard weaker derived summaries.

    Selective ingestion creates both ``*.text.md`` source passages and
    ``*.kg.md`` summaries for one upload.  A small answer model tends to copy
    unrelated examples from a broad KG summary even when a stronger raw-text
    chunk already answers the diagnostic question.  Prefer the primary route
    within the same upload, then remove the low-score tail instead of filling
    ``chunk_top_k`` with noise.
    """
    folded_query = query.casefold()
    if not any(term in folded_query for term in _DIAGNOSTIC_QUERY_TERMS):
        return ranked

    best_primary: dict[str, float] = {}
    for item in ranked:
        file_path = str(item.get("file_path") or "").casefold()
        if not file_path.endswith(".text.md"):
            continue
        score = float(item.get("rerank_score", 0.0))
        family = _source_family(item)
        best_primary[family] = max(best_primary.get(family, float("-inf")), score)

    filtered = []
    for item in ranked:
        file_path = str(item.get("file_path") or "").casefold()
        if file_path.endswith(".kg.md"):
            primary_score = best_primary.get(_source_family(item))
            if primary_score is not None:
                continue
        filtered.append(item)

    if not filtered:
        return ranked
    top_score = float(filtered[0].get("rerank_score", 0.0))
    minimum_top = float(os.getenv("RK_DIAGNOSTIC_MIN_TOP_SCORE", "0.5"))
    if top_score < minimum_top:
        return filtered
    relative_floor = float(os.getenv("RK_DIAGNOSTIC_RELATIVE_SCORE_FLOOR", "0.3"))
    score_floor = top_score * relative_floor
    focused = [
        item
        for item in filtered
        if float(item.get("rerank_score", 0.0)) >= score_floor
    ]
    max_chunks = max(1, int(os.getenv("RK_DIAGNOSTIC_MAX_CHUNKS", "2")))
    return (focused or filtered[:1])[:max_chunks]


def apply_source_authority_policy(
    chunks: list[dict[str, Any]],
    query: str = "",
) -> list[dict[str, Any]]:
    """Downweight derived and non-substantive evidence while retaining it."""
    patterns = [
        value.strip().casefold()
        for value in os.getenv("RK_DERIVED_SOURCE_PATTERNS", "技术方案").split(",")
        if value.strip()
    ]
    derived_penalty = float(os.getenv("RK_DERIVED_SOURCE_PENALTY", "0.2"))
    thin_penalty = float(os.getenv("RK_THIN_EVIDENCE_PENALTY", "0.25"))
    exact_terms: list[str] = []
    try:
        expansions = json.loads(os.getenv("RK_LEXICAL_QUERY_EXPANSIONS", "{}"))
        if isinstance(expansions, dict):
            folded_query = query.casefold()
            for trigger, terms in expansions.items():
                if str(trigger).casefold() not in folded_query:
                    continue
                values = terms if isinstance(terms, list) else [terms]
                exact_terms.extend(str(value).casefold() for value in values if value)
    except json.JSONDecodeError:
        pass
    boost_per_term = float(os.getenv("RK_EXACT_EVIDENCE_BOOST_PER_TERM", "0.4"))
    adjusted = []
    for index, chunk in enumerate(chunks):
        item = chunk.copy()
        raw_score = item.get("rerank_score")
        if raw_score is None:
            adjusted.append((index, item))
            continue
        score = float(raw_score)
        penalty = 1.0
        file_path = str(item.get("file_path") or "").casefold()
        if any(pattern in file_path for pattern in patterns):
            penalty *= derived_penalty
            item["source_authority"] = "derived"
        content = str(item.get("content") or "")
        named_item, named_match_count = _compact_named_numbered_item(query, content)
        if named_item:
            item["content"] = named_item
            item["named_item_compacted"] = True
            item["named_item_match_count"] = named_match_count
            content = named_item
        compact_section, section_match_count = _compact_named_sections(query, content)
        if compact_section:
            item["content"] = compact_section
            item["named_section_compacted"] = True
            item["named_section_match_count"] = section_match_count
            content = compact_section
        compact_diagnostic = _compact_diagnostic_table(query, content)
        if compact_diagnostic:
            item["content"] = compact_diagnostic
            item["diagnostic_table_compacted"] = True
            content = compact_diagnostic
        # Tiny question/example fragments can score highly by repeating the
        # query without containing an answer. Keep short commands exempt.
        if len(content.strip()) < 160 and "--" not in content and "/" not in content:
            penalty *= thin_penalty
            item["evidence_quality"] = "thin"
        folded_content = content.casefold()
        exact_hits = sum(1 for term in exact_terms if term in folded_content)
        exact_boost = 1.0 + min(exact_hits, 3) * boost_per_term if exact_hits >= 2 else 1.0
        table_boost = _table_evidence_boost(query, content)
        if table_boost > 1.0:
            compact_table = _compact_metric_table(query, content)
            if compact_table:
                item["content"] = compact_table
        if exact_hits:
            item["exact_evidence_hits"] = exact_hits
        item["raw_rerank_score"] = score
        item["rerank_score"] = score * penalty * exact_boost * table_boost
        item["source_penalty"] = penalty
        item["exact_evidence_boost"] = exact_boost
        item["table_evidence_boost"] = table_boost
        adjusted.append((index, item))
    adjusted.sort(
        key=lambda pair: (-float(pair[1].get("rerank_score", 0.0)), pair[0])
    )
    ranked = [item for _, item in adjusted]
    named_matches = [
        max(
            int(item.get("named_item_match_count", 0)),
            int(item.get("named_section_match_count", 0)),
        )
        for item in ranked
    ]
    best_named_match = max(named_matches, default=0)
    if best_named_match >= 1:
        ranked = [
            item
            for item in ranked
            if max(
                int(item.get("named_item_match_count", 0)),
                int(item.get("named_section_match_count", 0)),
            ) == best_named_match
        ]
    complete_tables = [
        item for item in ranked if float(item.get("table_evidence_boost", 1.0)) > 1.0
    ]
    # Once a self-contained table directly matches a metric question, extra
    # same-document rows, download lists and graph-adjacent chunks only dilute
    # the small model's attention. The table already carries its own schema.
    if complete_tables:
        return complete_tables
    return _filter_diagnostic_evidence(ranked, query)
