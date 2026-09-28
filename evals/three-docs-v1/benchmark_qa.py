#!/usr/bin/env python3
"""Measure serial Q&A latency, model calls, and native LLM token usage."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import statistics
import time
from urllib.request import urlopen

from run_eval import ROOT, SMOKE_IDS, percentile, post_stream


def metric_snapshot(url, after=0):
    with urlopen(url.rstrip("/") + f"/admin/chat-metrics?after={after}", timeout=5) as response:
        return json.load(response)


def summarize(records, query_model):
    llm_calls = [item for item in records if item.get("kind", "llm") == "llm"]
    final_calls = [item for item in llm_calls if item["model"] == query_model]
    auxiliary = [item for item in llm_calls if item["model"] != query_model]
    embedding_calls = [item for item in records if item.get("kind") == "embedding"]
    rerank_calls = [item for item in records if item.get("kind") == "rerank"]

    def token_sum(calls, key):
        values = [item.get(key) for item in calls]
        return sum(values) if values and all(value is not None for value in values) else None

    return {
        "model_calls": len(llm_calls),
        "final_calls": final_calls,
        "auxiliary_calls": auxiliary,
        "embedding_calls": embedding_calls,
        "rerank_calls": rerank_calls,
        "embedding_call_count": len(embedding_calls),
        "rerank_call_count": len(rerank_calls),
        "embedding_ms": round(sum(item["elapsed_ms"] for item in embedding_calls), 1),
        "rerank_ms": round(sum(item["elapsed_ms"] for item in rerank_calls), 1),
        "embedding_input_items": sum(item["input_items"] for item in embedding_calls),
        "rerank_candidates": sum(item["candidate_count"] for item in rerank_calls),
        "embedding_input_tokens": token_sum(embedding_calls, "input_tokens"),
        "rerank_input_tokens": token_sum(rerank_calls, "input_tokens"),
        "final_input_tokens": token_sum(final_calls, "input_tokens"),
        "final_output_tokens": token_sum(final_calls, "output_tokens"),
        "all_llm_input_tokens": token_sum(llm_calls, "input_tokens"),
        "all_llm_output_tokens": token_sum(llm_calls, "output_tokens"),
        "usage_note": "no_model_call" if not llm_calls else (
            "native_usage_missing" if any(
                item.get("input_tokens") is None or item.get("output_tokens") is None
                for item in llm_calls
            ) else "native_usage"
        ),
    }


def aggregate(results, wall_seconds):
    valid = [item for item in results if not item["error"]]

    def distribution(key):
        values = [item[key] for item in valid if item.get(key) is not None]
        return {
            "count": len(values),
            "median": round(statistics.median(values), 1) if values else None,
            "p95": percentile(values, 0.95),
            "min": min(values) if values else None,
            "max": max(values) if values else None,
        }

    return {
        "requested": len(results),
        "successful": len(valid),
        "errors": len(results) - len(valid),
        "single_client_queries_per_minute": round(len(valid) * 60 / wall_seconds, 2),
        "ttft_ms": distribution("ttft_ms"),
        "total_ms": distribution("total_ms"),
        "final_input_tokens": distribution("final_input_tokens"),
        "final_output_tokens": distribution("final_output_tokens"),
        "all_llm_input_tokens": distribution("all_llm_input_tokens"),
        "all_llm_output_tokens": distribution("all_llm_output_tokens"),
        "embedding_ms": distribution("embedding_ms"),
        "rerank_ms": distribution("rerank_ms"),
        "embedding_input_tokens": distribution("embedding_input_tokens"),
        "rerank_input_tokens": distribution("rerank_input_tokens"),
        "embedding_call_count": distribution("embedding_call_count"),
        "rerank_call_count": distribution("rerank_call_count"),
        "rerank_candidates": distribution("rerank_candidates"),
        "native_usage_available": sum(item["usage_note"] == "native_usage" for item in results),
        "no_model_call": sum(item["usage_note"] == "no_model_call" for item in results),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9621")
    parser.add_argument("--gateway-url", default="http://127.0.0.1:8100")
    parser.add_argument("--query-model", default="qwen3.5-2b-query")
    parser.add_argument(
        "--mode",
        choices=["local", "global", "hybrid", "naive", "mix", "bypass"],
        default="mix",
        help="LightRAG query mode; default: mix",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--ids", nargs="+", help="case IDs; default is the nine-case smoke set")
    selection.add_argument("--question", help="run one custom question")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument(
        "--user-prompt",
        help="optional per-request LightRAG user prompt; overrides the server default",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")

    dataset = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    cases = {item["id"]: item for item in dataset["cases"]}
    if args.question:
        cases["CUSTOM"] = {"id": "CUSTOM", "question": args.question}
    args.ids = ["CUSTOM"] if args.question else (args.ids or SMOKE_IDS)
    unknown = [case_id for case_id in args.ids if case_id not in cases]
    if unknown:
        parser.error("unknown case IDs: " + ", ".join(unknown))
    output = args.output or ROOT / "results" / (
        "qa-performance-" + datetime.now().astimezone().strftime("%Y%m%d-%H%M%S%z") + ".json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "mode": args.mode, "stream": True, "include_references": True,
        "include_chunk_content": True, "include_progress": True,
        "enable_rerank": True, "top_k": 6, "chunk_top_k": 3,
        "max_entity_tokens": 500, "max_relation_tokens": 300,
        "max_total_tokens": 3000, "conversation_history": [],
    }
    if args.user_prompt is not None:
        config["user_prompt"] = args.user_prompt
    initial = metric_snapshot(args.gateway_url)
    report = {
        "started_at": datetime.now().astimezone().isoformat(),
        "conditions": {
            "url": args.url, "gateway_url": args.gateway_url,
            "query_model": args.query_model, "concurrency": 1,
            "repeat": args.repeat, "case_ids": args.ids,
            "query_config": config,
            "token_definition": "Native LLM usage and RKNN3 n_prefill_tokens for vector models; items, characters, and candidate counts are retained as workload dimensions."
        },
        "results": [],
    }

    def persist():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    persist()
    run_started = time.monotonic()
    sequence = initial["latest_sequence"]
    for repetition in range(1, args.repeat + 1):
        for case_id in args.ids:
            case = cases[case_id]
            measured = post_stream(args.url, {"query": case["question"], **config}, args.timeout)
            snapshot = metric_snapshot(args.gateway_url, sequence)
            sequence = snapshot["latest_sequence"]
            usage = summarize(snapshot["records"], args.query_model)
            item = {
                "case_id": case_id, "repetition": repetition,
                "question": case["question"],
                "ttft_ms": measured["ttft_ms"], "total_ms": measured["total_ms"],
                "http_status": measured["http_status"], "error": measured["error"],
                "answer": measured["answer"], "reference_count": len(measured["references"]),
                **usage,
            }
            report["results"].append(item)
            persist()
            print(
                f"{case_id}#{repetition}: {item['total_ms']} ms, "
                f"TTFT {item['ttft_ms']} ms, "
                f"final tokens {item['final_input_tokens']}/{item['final_output_tokens']}, "
                f"LLM calls {item['model_calls']}, "
                f"embedding {item['embedding_call_count']} calls/"
                f"{item['embedding_input_tokens']} tokens/{item['embedding_ms']} ms, "
                f"rerank {item['rerank_call_count']} calls/"
                f"{item['rerank_input_tokens']} tokens/{item['rerank_ms']} ms, "
                f"{item['usage_note']}", flush=True,
            )
    report["finished_at"] = datetime.now().astimezone().isoformat()
    report["summary"] = aggregate(report["results"], time.monotonic() - run_started)
    persist()
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"JSON: {output}")


if __name__ == "__main__":
    main()
