#!/usr/bin/env python3
"""Observe query-stream events and gateway call completion timestamps on a board."""

import argparse
import json
import threading
import time
from urllib.request import Request, urlopen


GATEWAY = "http://127.0.0.1:8100"
RAG = "http://127.0.0.1:9621"
QUESTION = "FT 测试中 USB 错误是为什么？"


def snapshot(after):
    with urlopen(f"{GATEWAY}/admin/chat-metrics?after={after}", timeout=5) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["naive", "mix"], default="naive")
    parser.add_argument("--question", default=QUESTION)
    parser.add_argument("--variant", action="store_true", help="use an uncached USB wording")
    args = parser.parse_args()
    question = "FT 测试时出现 USB 错误，原因是什么？" if args.variant else args.question
    initial = snapshot(0)["latest_sequence"]
    origin = time.monotonic()
    observed = []
    stopping = threading.Event()

    def poll():
        sequence = initial
        while not stopping.is_set():
            try:
                current = snapshot(sequence)
                now = (time.monotonic() - origin) * 1000
                for item in current["records"]:
                    observed.append({
                        "event": "gateway_call_complete",
                        "at_ms": round(now, 1),
                        "start_estimate_ms": round(now - item["elapsed_ms"], 1),
                        "kind": item.get("kind", "llm"),
                        "elapsed_ms": item["elapsed_ms"],
                        "sequence": item["sequence"],
                    })
                sequence = current["latest_sequence"]
            except Exception as exc:
                observed.append({"event": "poll_error", "error": str(exc)})
            stopping.wait(0.02)

    watcher = threading.Thread(target=poll, daemon=True)
    watcher.start()
    config = {
        "query": question, "mode": args.mode, "stream": True,
        "include_references": True, "include_chunk_content": True,
        "include_progress": True, "enable_rerank": True,
        "top_k": 6, "chunk_top_k": 3, "max_entity_tokens": 500,
        "max_relation_tokens": 300, "max_total_tokens": 3000,
        "conversation_history": [],
    }
    request = Request(
        f"{RAG}/query/stream",
        data=json.dumps(config, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/x-ndjson"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            first_answer = False
            for line in response:
                now = round((time.monotonic() - origin) * 1000, 1)
                event = json.loads(line)
                if event.get("progress"):
                    observed.append({"event": "progress", "at_ms": now, "value": event["progress"]})
                if event.get("response") and not first_answer:
                    observed.append({"event": "first_answer", "at_ms": now})
                    first_answer = True
                if event.get("references"):
                    observed.append({"event": "references", "at_ms": now})
                if event.get("error"):
                    observed.append({"event": "error", "at_ms": now, "value": event["error"]})
    finally:
        observed.append({"event": "client_end", "at_ms": round((time.monotonic() - origin) * 1000, 1)})
        stopping.set()
        watcher.join(timeout=1)
    final = snapshot(initial)
    known = {item["sequence"] for item in observed if item.get("sequence") is not None}
    for item in final["records"]:
        if item["sequence"] not in known:
            now = round((time.monotonic() - origin) * 1000, 1)
            observed.append({
                "event": "gateway_call_complete_by_client_end",
                "at_ms": now,
                "start_estimate_ms": round(now - item["elapsed_ms"], 1),
                "kind": item.get("kind", "llm"),
                "elapsed_ms": item["elapsed_ms"],
                "sequence": item["sequence"],
            })
    print(json.dumps(sorted(observed, key=lambda e: e.get("at_ms", 0)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
