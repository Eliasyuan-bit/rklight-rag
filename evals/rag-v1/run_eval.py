#!/usr/bin/env python3
"""Run the RAG regression questions against LightRAG's streaming API."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import statistics
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SMOKE_IDS = ["FT01", "FT04", "FT06", "FT07", "DEP01", "DEP06", "AUTH02", "AUTH08", "NEG01", "NEG02"]


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def post_stream(url, payload, timeout):
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url.rstrip("/") + "/query/stream",
        data=encoded,
        headers={"Content-Type": "application/json", "Accept": "application/x-ndjson"},
        method="POST",
    )
    started = time.monotonic()
    answer_parts, references, progress, raw_events = [], [], [], []
    ttft_ms = None
    server_response_time_s = None
    stream_error = None
    status = None
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    raw_events.append({"invalid_json": line})
                    stream_error = "invalid NDJSON event"
                    continue
                raw_events.append(event)
                if "progress" in event:
                    progress.append(event["progress"])
                if "references" in event:
                    references = event["references"] or []
                if "response" in event and event["response"]:
                    if ttft_ms is None:
                        ttft_ms = round((time.monotonic() - started) * 1000, 1)
                    answer_parts.append(event["response"])
                if "response_time" in event:
                    server_response_time_s = event["response_time"]
                if "error" in event:
                    stream_error = str(event["error"])
    except HTTPError as exc:
        status = exc.code
        stream_error = exc.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError) as exc:
        stream_error = str(exc)
    total_ms = round((time.monotonic() - started) * 1000, 1)
    return {
        "answer": "".join(answer_parts),
        "references": references,
        "progress": progress,
        "ttft_ms": ttft_ms,
        "total_ms": total_ms,
        "server_response_time_s": server_response_time_s,
        "http_status": status,
        "finish_reason": None,
        "finish_reason_note": "LightRAG NDJSON endpoint does not expose the model finish reason",
        "error": stream_error,
        "raw_events": raw_events,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9621", help="LightRAG base URL")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--smoke", action="store_true", help="run the recommended 10-case smoke set")
    group.add_argument("--ids", nargs="+", help="run selected case IDs")
    parser.add_argument("--mode", choices=["local", "global", "hybrid", "naive", "mix", "bypass"], default="hybrid")
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--chunk-top-k", type=int, default=3)
    parser.add_argument("--max-entity-tokens", type=int, default=500)
    parser.add_argument("--max-relation-tokens", type=int, default=300)
    parser.add_argument("--max-total-tokens", type=int, default=3000)
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--output", help="result JSON path; defaults under results/")
    parser.add_argument("--label", default="baseline", help="short run label")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    dataset = json.loads((root / "cases.json").read_text())
    case_map = {case["id"]: case for case in dataset["cases"]}
    selected_ids = SMOKE_IDS if args.smoke else (args.ids or list(case_map))
    unknown = [case_id for case_id in selected_ids if case_id not in case_map]
    if unknown:
        parser.error("unknown case IDs: " + ", ".join(unknown))

    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S%z")
    run_id = f"{args.label}-{timestamp}"
    output = Path(args.output) if args.output else root / "results" / f"{run_id}.json"
    query_config = {
        "mode": args.mode,
        "stream": True,
        "include_references": True,
        "include_chunk_content": True,
        "include_progress": True,
        "enable_rerank": not args.no_rerank,
        "top_k": args.top_k,
        "chunk_top_k": args.chunk_top_k,
        "max_entity_tokens": args.max_entity_tokens,
        "max_relation_tokens": args.max_relation_tokens,
        "max_total_tokens": args.max_total_tokens,
        "conversation_history": [],
    }
    run = {
        "run_id": run_id,
        "dataset_version": dataset["version"],
        "started_at": datetime.now().astimezone().isoformat(),
        "url": args.url,
        "query_config": query_config,
        "cache_condition": "uncontrolled; existing LightRAG cache is preserved",
        "results": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)

    for position, case_id in enumerate(selected_ids, 1):
        case = case_map[case_id]
        payload = {"query": case["question"], **query_config}
        print(f"[{position}/{len(selected_ids)}] {case_id} {case['question']}", flush=True)
        measured = post_stream(args.url, payload, args.timeout)
        result = {
            "case_id": case_id,
            "question": case["question"],
            **measured,
            "final_context_chunk_ids": None,
            "scores": {name: None for name in ("retrieval", "correctness", "completeness", "citation", "format", "answerability")},
            "violations": [],
            "review_notes": "待人工评分",
        }
        run["results"].append(result)
        output.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n")
        state = "ERROR" if result["error"] else "OK"
        print(f"  {state} TTFT={result['ttft_ms']}ms total={result['total_ms']}ms refs={len(result['references'])}", flush=True)

    run["finished_at"] = datetime.now().astimezone().isoformat()
    valid = [r for r in run["results"] if not r["error"]]
    ttfts = [r["ttft_ms"] for r in valid if r["ttft_ms"] is not None]
    totals = [r["total_ms"] for r in valid]
    run["summary"] = {
        "requested": len(selected_ids),
        "completed_without_api_error": len(valid),
        "errors": len(selected_ids) - len(valid),
        "ttft_ms_median": round(statistics.median(ttfts), 1) if ttfts else None,
        "ttft_ms_p95_nearest_rank": percentile(ttfts, 0.95),
        "total_ms_median": round(statistics.median(totals), 1) if totals else None,
        "total_ms_p95_nearest_rank": percentile(totals, 0.95),
        "note": "Latency includes queueing and retrieval. Quality scores require human review.",
    }
    output.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n")
    print(f"Result: {output}")
    print(json.dumps(run["summary"], ensure_ascii=False, indent=2))
    return 1 if run["summary"]["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
