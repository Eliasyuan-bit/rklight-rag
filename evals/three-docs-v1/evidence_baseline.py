"""Shared evidence-level assessment helpers for the three-document RAG eval.

The helpers intentionally do not try to judge answer semantics with keyword
matching.  They only derive facts observable in an API result, then preserve
explicit reviewer decisions for retrieval, evidence and answer quality.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any


ASSESSMENT_VALUES = ("pass", "fail", "unknown")
FAILURE_TYPES = (
    "pass",
    "api_error",
    "retrieval_miss",
    "context_loss",
    "evidence_insufficient",
    "generation_error",
    "not_reviewed",
)


def trace_id(question: str) -> str:
    """Match the privacy-safe trace id emitted by the LightRAG retrieval hook."""
    return hashlib.sha256(question.encode("utf-8")).hexdigest()[:12]


def _canonical_source(value: object) -> str:
    """Normalize generated `.kg.md` / `.text.md` names to source filenames."""
    name = Path(str(value or "")).name
    for marker in (".kg.md", ".text.md"):
        if name.endswith(marker):
            return name[: -len(marker)] + ".md"
    return name


def _reference_text(references: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for reference in references:
        content = reference.get("content", [])
        if isinstance(content, list):
            parts.extend(str(value) for value in content)
        elif content:
            parts.append(str(content))
    return "\n".join(parts)


def empty_review() -> dict[str, str]:
    """Return the explicit reviewer fields stored alongside one answer."""
    return {
        "retrieval_hit": "unknown",
        "evidence_complete": "unknown",
        "grounded": "unknown",
        "answer_correct": "unknown",
        "primary_failure": "not_reviewed",
        "notes": "",
    }


def hydrate_item(item: dict[str, Any], case: dict[str, Any], source_files: dict[str, str]) -> None:
    """Add P0 metadata to a historical run without changing its answer data."""
    item.setdefault("expected_source", source_files.get(str(case.get("source") or ""), ""))
    item.setdefault("retrieval_trace_id", trace_id(str(item.get("question") or case.get("question") or "")))
    item.setdefault("assessment", empty_review())


def automatic_assessment(item: dict[str, Any]) -> dict[str, Any]:
    """Derive only observable evidence signals; unknown is preferred to guesses."""
    references = item.get("references") or []
    expected_source = _canonical_source(item.get("expected_source") or item.get("source_file"))
    cited_sources = sorted({_canonical_source(reference.get("file_path")) for reference in references})
    source_match = bool(expected_source and expected_source in cited_sources)
    quoted_text = _reference_text(references)
    evidence = item.get("evidence") or []
    quote_hits = [
        str(evidence_item.get("quote") or "")
        for evidence_item in evidence
        if str(evidence_item.get("quote") or "")
        and str(evidence_item.get("quote") or "") in quoted_text
    ]
    required_quotes = [str(evidence_item.get("quote") or "") for evidence_item in evidence]
    return {
        "api_ok": not bool(item.get("error")) and item.get("http_status") in (None, 200),
        "reference_count": len(references),
        "cited_sources": cited_sources,
        "expected_source": expected_source or None,
        "expected_source_cited": source_match if expected_source else None,
        "visible_evidence_quote_hits": quote_hits,
        "visible_evidence_quote_total": len(required_quotes),
        # Citation snippets can be shortened by the server.  A missing quote is
        # therefore deliberately `unknown`, never automatic evidence failure.
        "final_evidence_visible": (
            "pass" if required_quotes and len(quote_hits) == len(required_quotes) else "unknown"
        ),
    }


def normalize_review(raw: object) -> dict[str, str]:
    """Keep old runs readable and reject accidental free-form verdict values."""
    review = empty_review()
    if not isinstance(raw, dict):
        return review
    for field in ("retrieval_hit", "evidence_complete", "grounded", "answer_correct"):
        value = str(raw.get(field, review[field]))
        review[field] = value if value in ASSESSMENT_VALUES else "unknown"
    failure = str(raw.get("primary_failure", review["primary_failure"]))
    review["primary_failure"] = failure if failure in FAILURE_TYPES else "not_reviewed"
    review["notes"] = str(raw.get("notes", ""))
    return review


def assessment_for_item(item: dict[str, Any]) -> dict[str, Any]:
    """Return immutable automatic observations plus normalized manual review."""
    automatic = automatic_assessment(item)
    review = normalize_review(item.get("assessment"))
    if not automatic["api_ok"]:
        review["primary_failure"] = "api_error"
        if review["answer_correct"] == "unknown":
            review["answer_correct"] = "fail"
    return {"automatic": automatic, "review": review}


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize reviewed and unreviewed evidence outcomes without guessing."""
    assessments = [assessment_for_item(item) for item in items]
    reviews = [assessment["review"] for assessment in assessments]
    return {
        "cases": len(items),
        "api_ok": sum(assessment["automatic"]["api_ok"] for assessment in assessments),
        "expected_source_cited": sum(
            assessment["automatic"]["expected_source_cited"] is True for assessment in assessments
        ),
        "visible_all_required_quotes": sum(
            assessment["automatic"]["final_evidence_visible"] == "pass" for assessment in assessments
        ),
        "reviewed": sum(review["primary_failure"] != "not_reviewed" for review in reviews),
        "retrieval_hit": dict(Counter(review["retrieval_hit"] for review in reviews)),
        "evidence_complete": dict(Counter(review["evidence_complete"] for review in reviews)),
        "grounded": dict(Counter(review["grounded"] for review in reviews)),
        "answer_correct": dict(Counter(review["answer_correct"] for review in reviews)),
        "primary_failure": dict(Counter(review["primary_failure"] for review in reviews)),
    }
