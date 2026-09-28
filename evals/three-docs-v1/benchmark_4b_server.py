#!/usr/bin/env python3
"""Measure a warm single-card RKLLM server at exact native prompt token counts."""

import argparse
import json
import statistics
import time
from urllib.request import Request, urlopen


URL = "http://127.0.0.1:8080/v1/chat/completions"
INTRO = (
    "Continue the numbered sequence from 1 to 500, one short item per line. "
    "Do not stop before item 500. Context:"
)


def request_tokens(repetitions, output_limit):
    content = INTRO + " a" * repetitions
    body = {
        "model": "qwen3.5-4b",
        "messages": [{"role": "user", "content": content}],
        "max_tokens": output_limit,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
        "cache_prompt": False,
    }
    request = Request(
        URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    started = time.monotonic()
    first_content_ms = None
    final = None
    with urlopen(request, timeout=120) as response:
        for line in response:
            if not line.startswith(b"data: "):
                continue
            payload = line[6:].strip()
            if payload == b"[DONE]":
                break
            event = json.loads(payload)
            delta = event.get("choices", [{}])[0].get("delta") or {}
            if delta.get("content") and first_content_ms is None:
                first_content_ms = (time.monotonic() - started) * 1000
            if event.get("usage"):
                final = event
    if final is None:
        raise RuntimeError("stream ended without native usage/timings")
    usage = final["usage"]
    timings = final.get("timings") or {}
    return {
        "prompt_tokens": usage["prompt_tokens"],
        "output_tokens": usage["completion_tokens"],
        "ttft_ms": round(first_content_ms, 1) if first_content_ms is not None else None,
        "total_ms": round((time.monotonic() - started) * 1000, 1),
        "prompt_ms": timings.get("prompt_ms"),
        "prefill_tps": timings.get("prompt_per_second"),
        "predicted_ms": timings.get("predicted_ms"),
        "decode_tps": timings.get("predicted_per_second"),
        "finish_reason": final.get("choices", [{}])[0].get("finish_reason"),
        "repetitions": repetitions,
    }


def calibrate(target):
    repetitions = max(target - 40, 1)
    for attempt in range(1, 7):
        measured = request_tokens(repetitions, 1)
        observed = measured["prompt_tokens"]
        print(json.dumps({"calibration_target": target, "attempt": attempt,
                          "repetitions": repetitions, "observed": observed}), flush=True)
        if observed == target:
            return repetitions
        repetitions += target - observed
        if repetitions < 1:
            raise RuntimeError(f"calibration moved below one repetition for {target}")
    raise RuntimeError(f"could not calibrate exactly to {target} input tokens")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", required=True,
                        help="input:output token target, e.g. 662:41")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    results = []
    for case in args.case:
        target_input, target_output = (int(value) for value in case.split(":"))
        repetitions = calibrate(target_input)
        warmup = request_tokens(repetitions, target_output)
        print(json.dumps({"case": case, "warmup": warmup}), flush=True)
        for run in range(1, args.repeats + 1):
            result = request_tokens(repetitions, target_output)
            if result["prompt_tokens"] != target_input:
                raise RuntimeError(f"prompt token drift for {case}: {result['prompt_tokens']}")
            record = {"case": case, "run": run, **result}
            results.append(record)
            print(json.dumps(record), flush=True)
    print("SUMMARY")
    for case in args.case:
        rows = [row for row in results if row["case"] == case]
        print(json.dumps({
            "case": case,
            "samples": len(rows),
            "actual_output_tokens": [row["output_tokens"] for row in rows],
            "median_ttft_ms": round(statistics.median(row["ttft_ms"] for row in rows), 1),
            "median_prompt_ms": round(statistics.median(row["prompt_ms"] for row in rows), 1),
            "median_prefill_tps": round(statistics.median(row["prefill_tps"] for row in rows), 1),
            "median_decode_tps": round(statistics.median(row["decode_tps"] for row in rows), 1),
            "median_total_ms": round(statistics.median(row["total_ms"] for row in rows), 1),
        }), flush=True)


if __name__ == "__main__":
    main()
