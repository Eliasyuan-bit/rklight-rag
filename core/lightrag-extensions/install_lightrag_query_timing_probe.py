#!/usr/bin/env python3
"""Temporarily add fine-grained query timing logs to a deployed LightRAG operate.py.

Diagnostic hook for Naive and KG/Mix queries. The original file is backed up
before modification; this hook is intentionally not part of normal deployment.
"""

from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK_QUERY_TIMING_PROBE_V1"
HELPERS = '''# RK_QUERY_TIMING_PROBE_V1
import contextvars as _rk_contextvars
import time as _rk_time
import uuid as _rk_uuid

_rk_query_clock = _rk_contextvars.ContextVar("rk_query_clock", default=None)


def _rk_begin_timing(mode):
    stamp = (_rk_uuid.uuid4().hex[:8], mode, _rk_time.perf_counter())
    _rk_query_clock.set(stamp)
    _rk_timing_mark("begin", stamp)
    return stamp


def _rk_timing_mark(stage, stamp=None):
    stamp = stamp or _rk_query_clock.get()
    if stamp is not None:
        trace, mode, started = stamp
        logger.info(
            "RK_QUERY_TIMING trace=%s mode=%s stage=%s elapsed_ms=%.1f",
            trace, mode, stage, (_rk_time.perf_counter() - started) * 1000,
        )


async def _rk_timed_response(iterator, stamp):
    _rk_timing_mark("llm_stream_begin", stamp)
    first = True
    try:
        async for piece in iterator:
            if first:
                _rk_timing_mark("llm_stream_first", stamp)
                first = False
            yield piece
    finally:
        _rk_timing_mark("llm_stream_end", stamp)


'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def edit_section(
    source: str, start: str, end: str, edits: list[tuple[str, str, str]],
    *, last: bool = False,
) -> str:
    before, found, remaining = source.rpartition(start) if last else source.partition(start)
    if not found:
        raise SystemExit(f"missing section: {start.strip()}")
    section, found_end, after = remaining.partition(end) if end else (remaining, "", "")
    if end and not found_end:
        raise SystemExit(f"missing section end: {end.strip()}")
    section = start + section
    for old, new, label in edits:
        section = replace_once(section, old, new, label)
    return before + section + found_end + after


def instrument(source: str) -> str:
    if MARKER in source:
        raise SystemExit("timing probe already installed")
    source = replace_once(
        source,
        "from collections import Counter, defaultdict\n\n",
        "from collections import Counter, defaultdict\n\n" + HELPERS,
        "helper insertion",
    )
    source = edit_section(source, "async def naive_query(\n", "", [
        ('    if not query:\n        return QueryResult(content=PROMPTS["fail_response"])\n',
         '    _rk_stamp = _rk_begin_timing("naive")\n'
         '    if not query:\n        return QueryResult(content=PROMPTS["fail_response"])\n',
         "naive begin"),
        ('    chunks = await _get_vector_context(query, chunks_vdb, query_param, None)\n',
         '    chunks = await _get_vector_context(query, chunks_vdb, query_param, None)\n'
         '    _rk_timing_mark("retrieval_done", _rk_stamp)\n',
         "naive retrieval"),
        ('    query_tokens = await acount_tokens(tokenizer, query)\n',
         '    query_tokens = await acount_tokens(tokenizer, query)\n'
         '    _rk_timing_mark("token_budget_done", _rk_stamp)\n',
         "naive token budget"),
        ('    # Generate reference list from processed chunks using the new common function\n',
         '    _rk_timing_mark("candidate_processing_done", _rk_stamp)\n'
         '    # Generate reference list from processed chunks using the new common function\n',
         "naive candidate processing"),
        ('    if query_param.only_need_prompt:\n',
         '    _rk_timing_mark("prompt_build_done", _rk_stamp)\n'
         '    if query_param.only_need_prompt:\n',
         "naive prompt"),
        ('        response = await use_model_func(\n',
         '        _rk_timing_mark("llm_dispatch_begin", _rk_stamp)\n'
         '        response = await use_model_func(\n',
         "naive llm begin"),
        ('        # Streaming response (AsyncIterator)\n        return QueryResult(\n'
         '            response_iterator=response, raw_data=raw_data, is_streaming=True\n',
         '        # Streaming response (AsyncIterator)\n        return QueryResult(\n'
         '            response_iterator=_rk_timed_response(response, _rk_stamp),\n'
         '            raw_data=raw_data, is_streaming=True\n',
         "naive stream"),
    ], last=True)
    source = edit_section(source, "async def kg_query(\n", "async def get_keywords_from_query(\n", [
        ('    if not query:\n        return QueryResult(content=PROMPTS["fail_response"])\n',
         '    _rk_stamp = _rk_begin_timing(query_param.mode)\n'
         '    if not query:\n        return QueryResult(content=PROMPTS["fail_response"])\n',
         "kg begin"),
        ('    logger.debug(f"High-level keywords: {hl_keywords}")\n',
         '    _rk_timing_mark("keywords_done", _rk_stamp)\n'
         '    logger.debug(f"High-level keywords: {hl_keywords}")\n',
         "kg keywords"),
        ('    if context_result is None:\n',
         '    _rk_timing_mark("context_done", _rk_stamp)\n'
         '    if context_result is None:\n',
         "kg context"),
        ('    user_query = query\n\n    if query_param.only_need_prompt:\n',
         '    user_query = query\n    _rk_timing_mark("prompt_build_done", _rk_stamp)\n\n'
         '    if query_param.only_need_prompt:\n',
         "kg prompt"),
        ('        response = await use_model_func(\n',
         '        _rk_timing_mark("llm_dispatch_begin", _rk_stamp)\n'
         '        response = await use_model_func(\n',
         "kg llm begin"),
        ('            response_iterator=response,\n            raw_data=context_result.raw_data,\n',
         '            response_iterator=_rk_timed_response(response, _rk_stamp),\n'
         '            raw_data=context_result.raw_data,\n',
         "kg stream"),
    ])
    source = edit_section(source, "async def _build_query_context(\n", "async def _get_node_data(\n", [
        ('    # Stage 2: Apply token truncation for LLM efficiency\n',
         '    _rk_timing_mark("graph_search_done")\n'
         '    # Stage 2: Apply token truncation for LLM efficiency\n',
         "graph search"),
        ('    # Stage 3: Merge chunks using filtered entities/relations\n',
         '    _rk_timing_mark("token_truncation_done")\n'
         '    # Stage 3: Merge chunks using filtered entities/relations\n',
         "graph token truncation"),
        ('    if (\n        not merged_chunks\n',
         '    _rk_timing_mark("candidate_merge_done")\n'
         '    if (\n        not merged_chunks\n',
         "graph candidate merge"),
        ('    # Convert keywords strings to lists and add complete metadata to raw_data\n',
         '    _rk_timing_mark("context_render_done")\n'
         '    # Convert keywords strings to lists and add complete metadata to raw_data\n',
         "graph context render"),
    ])
    return source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operate_path", type=Path)
    parser.add_argument("--check", action="store_true", help="validate anchors without writing")
    args = parser.parse_args()
    path = args.operate_path
    original = path.read_text()
    modified = instrument(original)
    compile(modified, str(path), "exec")
    if args.check:
        print(f"timing probe anchors and syntax OK: {path}")
        return
    backup = path.with_suffix(path.suffix + ".before-rk-query-timing-probe")
    if backup.exists():
        raise SystemExit(f"backup already exists: {backup}")
    backup.write_text(original)
    path.write_text(modified)
    print(f"installed timing probe: {path}; backup: {backup}")


if __name__ == "__main__":
    main()
