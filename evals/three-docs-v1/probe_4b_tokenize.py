#!/usr/bin/env python3
"""Inspect whether rkllm3-server exposes an exact tokenizer endpoint."""

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


for endpoint, body in [
    ("/tokenize", {"content": "USB FT test error"}),
    ("/apply-template", {"messages": [{"role": "user", "content": "USB FT test error"}]}),
]:
    request = Request(
        "http://127.0.0.1:8080" + endpoint,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            print(endpoint, response.status, response.read(1000).decode())
    except HTTPError as exc:
        print(endpoint, exc.code, exc.read(1000).decode())
