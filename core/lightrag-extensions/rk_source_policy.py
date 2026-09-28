"""Post-rerank source authority policy for mixed-quality knowledge bases."""
from __future__ import annotations

import os
import json
from typing import Any


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
        # Tiny question/example fragments can score highly by repeating the
        # query without containing an answer. Keep short commands exempt.
        if len(content.strip()) < 160 and "--" not in content and "/" not in content:
            penalty *= thin_penalty
            item["evidence_quality"] = "thin"
        folded_content = content.casefold()
        exact_hits = sum(1 for term in exact_terms if term in folded_content)
        exact_boost = 1.0 + min(exact_hits, 3) * boost_per_term if exact_hits >= 2 else 1.0
        if exact_hits:
            item["exact_evidence_hits"] = exact_hits
        item["raw_rerank_score"] = score
        item["rerank_score"] = score * penalty * exact_boost
        item["source_penalty"] = penalty
        item["exact_evidence_boost"] = exact_boost
        adjusted.append((index, item))
    adjusted.sort(
        key=lambda pair: (-float(pair[1].get("rerank_score", 0.0)), pair[0])
    )
    return [item for _, item in adjusted]
