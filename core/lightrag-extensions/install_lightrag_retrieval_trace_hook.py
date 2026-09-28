#!/usr/bin/env python3
"""Install privacy-safe retrieval decision logs into pinned LightRAG source."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_RETRIEVAL_TRACE_V1"
FUNCTION_ANCHOR = "async def process_chunks_unified(\n"
FUNCTION_INSERT = '''# RK3588_RETRIEVAL_TRACE_V1
def _rk_log_chunk_stage(
    query: str,
    stage: str,
    chunks: list[dict],
    *,
    source_type: str = "mixed",
    input_count: int | None = None,
    requested_top_k: int | None = None,
    token_budget: int | None = None,
) -> None:
    """Log ranking decisions without logging query or evidence text."""
    import hashlib

    trace_id = hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]
    records = []
    for rank, chunk in enumerate(chunks, 1):
        record = {
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


async def process_chunks_unified(
'''
RERANK_ANCHOR = '''        unique_chunks = await apply_rerank_if_enabled(
            query=query,
            retrieved_docs=unique_chunks,
            global_config=global_config,
            enable_rerank=query_param.enable_rerank,
            top_n=rerank_top_k,
        )
'''
RERANK_INSERT = RERANK_ANCHOR + '''        _rk_log_chunk_stage(
            query,
            "reranked",
            unique_chunks,
            source_type=source_type,
            input_count=origin_count,
            requested_top_k=rerank_top_k,
            token_budget=chunk_token_limit,
        )
'''
TRUNCATE_ANCHOR = '''        unique_chunks = await run_in_tokenizer_executor(
            _truncate_chunks_for_unified_context,
            unique_chunks,
            chunk_token_limit,
            tokenizer,
        )

        logger.debug(
'''
TRUNCATE_INSERT = '''        unique_chunks = await run_in_tokenizer_executor(
            _truncate_chunks_for_unified_context,
            unique_chunks,
            chunk_token_limit,
            tokenizer,
        )
        _rk_log_chunk_stage(
            query,
            "final",
            unique_chunks,
            source_type=source_type,
            input_count=original_count,
            requested_top_k=query_param.chunk_top_k,
            token_budget=chunk_token_limit,
        )

        logger.debug(
'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise SystemExit(
            f"unsupported LightRAG source; expected one {label}, got {source.count(old)}"
        )
    return source.replace(old, new, 1)


def install(path: Path) -> None:
    source = path.read_text()
    if MARKER in source:
        print(f"already installed: {path}")
        return
    backup = path.with_suffix(path.suffix + ".before-rk3588-retrieval-trace")
    if not backup.exists():
        backup.write_text(source)
    source = replace_once(source, FUNCTION_ANCHOR, FUNCTION_INSERT, "process function")
    source = replace_once(source, RERANK_ANCHOR, RERANK_INSERT, "rerank call")
    source = replace_once(source, TRUNCATE_ANCHOR, TRUNCATE_INSERT, "truncation call")
    path.write_text(source)
    print(f"installed: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    install(args.path)


if __name__ == "__main__":
    main()
