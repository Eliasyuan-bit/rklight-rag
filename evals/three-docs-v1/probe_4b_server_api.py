#!/usr/bin/env python3
"""Inspect the on-board RKLLM 4B server's OpenAI streaming response."""

import json
import time
from urllib.request import Request, urlopen


body = {
    "model": "qwen3.5-4b",
    "messages": [{"role": "user", "content": "Briefly explain a USB test failure."}],
    "stream": True,
    "stream_options": {"include_usage": True},
    "max_tokens": 16,
    "temperature": 0,
}
request = Request(
    "http://127.0.0.1:8080/v1/chat/completions",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    method="POST",
)
started = time.monotonic()
with urlopen(request, timeout=90) as response:
    print("HTTP", response.status, response.headers.get("Content-Type"))
    for line in response:
        if line.startswith(b"data: "):
            print(round((time.monotonic() - started) * 1000, 1), line.decode().strip()[:1000])
