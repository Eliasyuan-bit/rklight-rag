#!/usr/bin/env python3
"""Install source-authority adjustment after LightRAG reranking."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_SOURCE_AUTHORITY_V10"
V9_MARKER = "# RK3588_SOURCE_AUTHORITY_V9"
V8_MARKER = "# RK3588_SOURCE_AUTHORITY_V8"
V7_MARKER = "# RK3588_SOURCE_AUTHORITY_V7"
V6_MARKER = "# RK3588_SOURCE_AUTHORITY_V6"
V5_MARKER = "# RK3588_SOURCE_AUTHORITY_V5"
V4_MARKER = "# RK3588_SOURCE_AUTHORITY_V4"
V3_MARKER = "# RK3588_SOURCE_AUTHORITY_V3"
V2_MARKER = "# RK3588_SOURCE_AUTHORITY_V2"
OLD_MARKER = "# RK3588_SOURCE_AUTHORITY_V1"
IMPORT_ANCHOR = (
    "from lightrag.exceptions import ChunkBlockMatchError, EmptyTruncatedResponseError\n"
)
IMPORT_INSERT = IMPORT_ANCHOR + (
    "from lightrag.rk_source_policy import apply_source_authority_policy\n"
    "from lightrag.rk_evidence_refiner import refine_evidence_units\n"
    "from lightrag.rk_evidence_refiner import apply_evidence_coverage_gate\n"
    "from lightrag.rk_evidence_refiner import apply_evidence_contract\n"
    "from lightrag.rk_evidence_refiner import recover_contract_evidence\n"
    "from lightrag.rk_evidence_refiner import apply_query_anchor_gate\n"
    "from lightrag.rk_lexical_retrieval import (\n"
    "    fuse_query_aware_rerank,\n"
    "    query_aware_rerank_top_n,\n"
    ")\n"
    "from lightrag.rk_table_parent import prioritize_typed_table_parents\n"
    "from lightrag.rk_section_parent import prioritize_section_parents\n"
)
RERANK_TRACE_ANCHOR = '''        _rk_log_chunk_stage(
            query,
            "reranked",
'''
RERANK_TRACE_INSERT = f'''        unique_chunks = fuse_query_aware_rerank(
            query, unique_chunks, rerank_top_k
        )
        unique_chunks = apply_source_authority_policy(unique_chunks, query)
        unique_chunks = await refine_evidence_units(unique_chunks, query)
        unique_chunks = apply_evidence_coverage_gate(unique_chunks, query)
        unique_chunks = apply_evidence_contract(unique_chunks, query)
        unique_chunks = apply_query_anchor_gate(unique_chunks, query)
        unique_chunks = recover_contract_evidence(unique_chunks, query, global_config)
        unique_chunks = apply_evidence_contract(unique_chunks, query)
        logger.info(
            "Source authority policy: adjusted=%d/%d",
            sum(1 for chunk in unique_chunks if chunk.get("source_penalty", 1.0) < 1.0),
            len(unique_chunks),
        )
        {MARKER}
        _rk_log_chunk_stage(
            query,
            "reranked",
'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise SystemExit(
            f"unsupported LightRAG source; expected one {label}, got {source.count(old)}"
        )
    return source.replace(old, new, 1)


def install(path: Path) -> None:
    source = path.read_text()
    if V9_MARKER in source:
        source = replace_once(
            source,
            "from lightrag.rk_evidence_refiner import recover_contract_evidence\n",
            "from lightrag.rk_evidence_refiner import recover_contract_evidence\n"
            "from lightrag.rk_evidence_refiner import apply_query_anchor_gate\n",
            "v9 query anchor import",
        )
        source = replace_once(
            source,
            "        unique_chunks = recover_contract_evidence(unique_chunks, query, global_config)\n"
            "        unique_chunks = apply_evidence_contract(unique_chunks, query)\n",
            "        unique_chunks = recover_contract_evidence(unique_chunks, query, global_config)\n"
            "        unique_chunks = apply_evidence_contract(unique_chunks, query)\n"
            "        unique_chunks = apply_query_anchor_gate(unique_chunks, query)\n",
            "v9 query anchor call",
        )
        source = source.replace(V9_MARKER, MARKER, 1)
        path.write_text(source)
        print(f"upgraded: {path}")
        return
    if V8_MARKER in source:
        source = replace_once(
            source,
            "from lightrag.rk_evidence_refiner import apply_evidence_contract\n",
            "from lightrag.rk_evidence_refiner import apply_evidence_contract\n"
            "from lightrag.rk_evidence_refiner import recover_contract_evidence\n",
            "v8 contract recovery import",
        )
        source = replace_once(
            source,
            "        unique_chunks = apply_evidence_contract(unique_chunks, query)\n",
            "        unique_chunks = apply_evidence_contract(unique_chunks, query)\n"
            "        unique_chunks = recover_contract_evidence(unique_chunks, query, global_config)\n"
            "        unique_chunks = apply_evidence_contract(unique_chunks, query)\n",
            "v8 contract recovery call",
        )
        source = source.replace(V8_MARKER, MARKER, 1)
        path.write_text(source)
        print(f"upgraded: {path}")
        return
    if V7_MARKER in source:
        source = replace_once(
            source,
            "from lightrag.rk_evidence_refiner import apply_evidence_coverage_gate\n",
            "from lightrag.rk_evidence_refiner import apply_evidence_coverage_gate\n"
            "from lightrag.rk_evidence_refiner import apply_evidence_contract\n",
            "v7 evidence contract import",
        )
        source = replace_once(
            source,
            "        unique_chunks = apply_evidence_coverage_gate(unique_chunks, query)\n",
            "        unique_chunks = apply_evidence_coverage_gate(unique_chunks, query)\n"
            "        unique_chunks = apply_evidence_contract(unique_chunks, query)\n",
            "v7 evidence contract call",
        )
        source = source.replace(V7_MARKER, MARKER, 1)
        path.write_text(source)
        print(f"upgraded: {path}")
        return
    if V6_MARKER in source:
        source = replace_once(
            source,
            "from lightrag.rk_evidence_refiner import refine_evidence_units\n",
            "from lightrag.rk_evidence_refiner import refine_evidence_units\n"
            "from lightrag.rk_evidence_refiner import apply_evidence_coverage_gate\n",
            "v6 evidence coverage import",
        )
        source = replace_once(
            source,
            "        unique_chunks = await refine_evidence_units(unique_chunks, query)\n",
            "        unique_chunks = await refine_evidence_units(unique_chunks, query)\n"
            "        unique_chunks = apply_evidence_coverage_gate(unique_chunks, query)\n",
            "v6 evidence coverage call",
        )
        source = source.replace(V6_MARKER, MARKER, 1)
        path.write_text(source)
        print(f"upgraded: {path}")
        return
    if MARKER in source:
        print(f"already installed: {path}")
        return
    if V5_MARKER in source:
        source = replace_once(
            source,
            "from lightrag.rk_table_parent import prioritize_typed_table_parents\n",
            "from lightrag.rk_table_parent import prioritize_typed_table_parents\n"
            "from lightrag.rk_section_parent import prioritize_section_parents\n",
            "v5 section parent import",
        )
        source = replace_once(
            source,
            "        unique_chunks = prioritize_typed_table_parents(unique_chunks, query)\n",
            "        unique_chunks = prioritize_typed_table_parents(unique_chunks, query)\n"
            "        unique_chunks = prioritize_section_parents(\n"
            "            unique_chunks, query, global_config\n"
            "        )\n",
            "v5 section parent selection",
        )
        source = source.replace(V5_MARKER, MARKER, 1)
        path.write_text(source)
        print(f"upgraded: {path}")
        return
    if V4_MARKER in source:
        source = replace_once(
            source,
            "from lightrag.rk_lexical_retrieval import (\n"
            "    fuse_query_aware_rerank,\n"
            "    query_aware_rerank_top_n,\n"
            ")\n",
            "from lightrag.rk_lexical_retrieval import (\n"
            "    fuse_query_aware_rerank,\n"
            "    query_aware_rerank_top_n,\n"
            ")\n"
            "from lightrag.rk_table_parent import prioritize_typed_table_parents\n",
            "v4 table parent import",
        )
        source = replace_once(
            source,
            "        rerank_top_k = query_param.chunk_top_k or len(unique_chunks)\n",
            "        unique_chunks = prioritize_typed_table_parents(unique_chunks, query)\n"
            "        rerank_top_k = query_param.chunk_top_k or len(unique_chunks)\n",
            "v4 pre-rerank table parent selection",
        )
        source = source.replace(V4_MARKER, V5_MARKER, 1)
        path.write_text(source)
        return install(path)
    if V3_MARKER in source:
        source = replace_once(
            source,
            "from lightrag.rk_evidence_refiner import refine_evidence_units\n",
            "from lightrag.rk_evidence_refiner import refine_evidence_units\n"
            "from lightrag.rk_lexical_retrieval import (\n"
            "    fuse_query_aware_rerank,\n"
            "    query_aware_rerank_top_n,\n"
            ")\n",
            "v3 query-aware import",
        )
        source = replace_once(
            source,
            "        rerank_top_k = query_param.chunk_top_k or len(unique_chunks)\n",
            "        rerank_top_k = query_param.chunk_top_k or len(unique_chunks)\n"
            "        rerank_candidate_k = query_aware_rerank_top_n(\n"
            "            query, unique_chunks, rerank_top_k\n"
            "        )\n",
            "v3 rerank candidate size",
        )
        source = replace_once(
            source,
            "            top_n=rerank_top_k,\n"
            "        )\n"
            "        unique_chunks = apply_source_authority_policy(unique_chunks, query)\n",
            "            top_n=rerank_candidate_k,\n"
            "        )\n"
            "        unique_chunks = fuse_query_aware_rerank(\n"
            "            query, unique_chunks, rerank_top_k\n"
            "        )\n"
            "        unique_chunks = apply_source_authority_policy(unique_chunks, query)\n",
            "v3 query-aware rerank call",
        )
        source = source.replace(V3_MARKER, MARKER, 1)
        path.write_text(source)
        print(f"upgraded: {path}")
        return
    if V2_MARKER in source:
        source = replace_once(
            source,
            "from lightrag.rk_source_policy import apply_source_authority_policy\n",
            "from lightrag.rk_source_policy import apply_source_authority_policy\n"
            "from lightrag.rk_evidence_refiner import refine_evidence_units\n",
            "v2 evidence refiner import",
        )
        source = replace_once(
            source,
            "        unique_chunks = apply_source_authority_policy(unique_chunks, query)\n",
            "        unique_chunks = apply_source_authority_policy(unique_chunks, query)\n"
            "        unique_chunks = await refine_evidence_units(unique_chunks, query)\n",
            "v2 evidence refiner call",
        )
        source = source.replace(V2_MARKER, V3_MARKER, 1)
        path.write_text(source)
        return install(path)
    if OLD_MARKER in source:
        source = replace_once(
            source,
            "apply_source_authority_policy(unique_chunks)",
            "apply_source_authority_policy(unique_chunks, query)",
            "v1 source policy call",
        )
        source = source.replace(OLD_MARKER, V2_MARKER, 1)
        path.write_text(source)
        return install(path)
    backup = path.with_suffix(path.suffix + ".before-rk3588-source-policy")
    if not backup.exists():
        backup.write_text(source)
    source = replace_once(source, IMPORT_ANCHOR, IMPORT_INSERT, "utils import")
    source = replace_once(
        source,
        "        rerank_top_k = query_param.chunk_top_k or len(unique_chunks)\n",
        "        unique_chunks = prioritize_typed_table_parents(unique_chunks, query)\n"
        "        unique_chunks = prioritize_section_parents(\n"
        "            unique_chunks, query, global_config\n"
        "        )\n"
        "        rerank_top_k = query_param.chunk_top_k or len(unique_chunks)\n"
        "        rerank_candidate_k = query_aware_rerank_top_n(\n"
        "            query, unique_chunks, rerank_top_k\n"
        "        )\n",
        "rerank candidate size",
    )
    source = replace_once(
        source,
        "            top_n=rerank_top_k,\n"
        "        )\n"
        + RERANK_TRACE_ANCHOR,
        "            top_n=rerank_candidate_k,\n"
        "        )\n"
        + RERANK_TRACE_ANCHOR,
        "rerank candidate argument",
    )
    source = replace_once(
        source, RERANK_TRACE_ANCHOR, RERANK_TRACE_INSERT, "rerank trace"
    )
    path.write_text(source)
    print(f"installed: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    install(args.path)


if __name__ == "__main__":
    main()
