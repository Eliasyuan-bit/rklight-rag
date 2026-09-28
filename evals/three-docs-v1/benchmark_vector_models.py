#!/usr/bin/env python3
"""Benchmark the board embedding and reranker through the model gateway."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import statistics
import time
from urllib.request import Request, urlopen


def request_json(url: str, payload: dict | None = None, timeout: float = 120) -> dict:
    if payload is None:
        request = Request(url)
    else:
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def fixed_text(length: int, prefix: str = "") -> str:
    seed = "岩芯平台检索增强生成模型性能测试文本包含型号命令错误原因流程表格数据"
    return (prefix + seed * ((length + len(seed)) // len(seed)))[:length]


def metric_after(base_url: str, sequence: int, kind: str) -> tuple[dict, int]:
    snapshot = request_json(
        base_url.rstrip("/") + f"/admin/chat-metrics?after={sequence}"
    )
    records = [record for record in snapshot["records"] if record.get("kind") == kind]
    if not records:
        raise RuntimeError(f"gateway did not record a {kind} metric")
    return records[-1], snapshot["latest_sequence"]


def summarize(samples: list[dict], units: int, chars: int) -> dict:
    internal = [sample["internal_ms"] for sample in samples]
    client = [sample["client_ms"] for sample in samples]
    median_internal = statistics.median(internal)
    summary = {
        "repeats": len(samples),
        "internal_ms_median": round(median_internal, 2),
        "internal_ms_p95": round(percentile(internal, 0.95), 2),
        "internal_ms_min": round(min(internal), 2),
        "internal_ms_max": round(max(internal), 2),
        "client_ms_median": round(statistics.median(client), 2),
        "units_per_second": round(units * 1000 / median_internal, 2),
        "chars_per_second": round(chars * 1000 / median_internal, 2),
        "samples": samples,
    }
    token_counts = [sample.get("input_tokens") for sample in samples]
    if token_counts and all(value is not None for value in token_counts):
        summary["input_tokens"] = token_counts[0]
        summary["input_tokens_per_second"] = round(
            statistics.median(sample["input_tps"] for sample in samples), 2
        )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-url", default="http://127.0.0.1:8100")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")

    base = args.gateway_url.rstrip("/")
    latest = request_json(base + "/admin/chat-metrics")["latest_sequence"]
    report = {
        "started_at": datetime.now().astimezone().isoformat(),
        "gateway_url": base,
        "repeats": args.repeats,
        "token_note": (
            "Token counts and effective input TPS come from native RKNN3 "
            "n_prefill_tokens when the deployed vector daemons support them. "
            "Each point has one unreported warmup."
        ),
        "embedding": [],
        "rerank": [],
    }

    def post_and_measure(path: str, payload: dict, kind: str) -> dict:
        nonlocal latest
        started = time.monotonic()
        request_json(base + path, payload)
        client_ms = (time.monotonic() - started) * 1000
        metric, latest = metric_after(base, latest, kind)
        return {
            "internal_ms": round(float(metric["elapsed_ms"]), 3),
            "client_ms": round(client_ms, 3),
            "input_tokens": metric.get("input_tokens"),
            "input_tps": metric.get("input_tps"),
        }

    embedding_cases = [
        *(dict(profile="batch", batch_size=batch, chars_per_item=128)
          for batch in (1, 3, 8, 16)),
        *(dict(profile="length", batch_size=1, chars_per_item=chars)
          for chars in (32, 512)),
    ]
    for case in embedding_cases:
        texts = [fixed_text(case["chars_per_item"], f"样本{i}：")
                 for i in range(case["batch_size"])]
        payload = {"model": "qwen3-embedding-0.6b", "input": texts}
        post_and_measure("/v1/embeddings", payload, "embedding")
        samples = [post_and_measure("/v1/embeddings", payload, "embedding")
                   for _ in range(args.repeats)]
        total_chars = sum(map(len, texts))
        result = {
            **case,
            "total_chars": total_chars,
            "vector_dimensions": 1024,
            **summarize(samples, len(texts), total_chars),
        }
        report["embedding"].append(result)
        print("embedding", json.dumps(result, ensure_ascii=False), flush=True)

    rerank_cases = [
        *(dict(profile="candidates", candidate_count=count, chars_per_candidate=256)
          for count in (1, 3, 6, 12, 24)),
        *(dict(profile="length", candidate_count=6, chars_per_candidate=chars)
          for chars in (64, 512)),
    ]
    query = "FT测试中USB错误是什么原因"
    for case in rerank_cases:
        documents = [fixed_text(case["chars_per_candidate"], f"候选{i}：")
                     for i in range(case["candidate_count"])]
        payload = {
            "model": "qwen3-reranker-0.6b",
            "query": query,
            "documents": documents,
        }
        post_and_measure("/v1/rerank", payload, "rerank")
        samples = [post_and_measure("/v1/rerank", payload, "rerank")
                   for _ in range(args.repeats)]
        total_chars = sum(map(len, documents))
        result = {
            **case,
            "query_chars": len(query),
            "total_candidate_chars": total_chars,
            **summarize(samples, len(documents), total_chars),
        }
        report["rerank"].append(result)
        print("rerank", json.dumps(result, ensure_ascii=False), flush=True)

    report["finished_at"] = datetime.now().astimezone().isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"JSON: {args.output}")


if __name__ == "__main__":
    main()
