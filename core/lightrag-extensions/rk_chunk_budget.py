"""Guarantee a bounded evidence chunk when whole-chunk truncation drops all."""
from __future__ import annotations

from typing import Any, Callable


def fit_first_evidence_chunk(
    chunks: list[dict[str, Any]],
    max_tokens: int,
    tokenizer: Any,
    generate_references: Callable,
    render_chunks: Callable,
) -> list[dict[str, Any]]:
    """Trim only the top-ranked chunk so at least one evidence item can fit."""
    if not chunks or max_tokens <= 0:
        return []
    candidate = chunks[0].copy()
    content = str(candidate.get("content") or "")
    if not content:
        return []

    candidate["content"] = ""
    _, empty_render_chunks = generate_references([candidate])
    overhead = len(tokenizer.encode(render_chunks(empty_render_chunks)))
    content_budget = max_tokens - overhead
    if content_budget <= 0:
        return []

    span = tokenizer.truncate_by_token_limit(content, content_budget)
    candidate["content"] = content[: span.end].rstrip()
    for _ in range(16):
        _, rendered_chunks = generate_references([candidate])
        rendered = render_chunks(rendered_chunks)
        actual_tokens = len(tokenizer.encode(rendered))
        if candidate["content"] and actual_tokens <= max_tokens:
            return [candidate]
        current_tokens = len(tokenizer.encode(candidate["content"]))
        next_budget = current_tokens - max(1, actual_tokens - max_tokens + 1)
        if next_budget <= 0:
            return []
        span = tokenizer.truncate_by_token_limit(content, next_budget)
        candidate["content"] = content[: span.end].rstrip()
    return []
