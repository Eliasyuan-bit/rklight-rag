#!/usr/bin/env python3
"""Upgrade the FIFO query gate with per-browser anonymous queue progress."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


V2 = "# RK3588_QUERY_FIFO_GATE_V2"
V3 = "# RK3588_QUERY_FIFO_GATE_V3"

COORDINATOR = '''    # RK3588_QUERY_FIFO_GATE_V3
    # WORKERS=1: one FIFO protects the shared multi-card LLM.
    class QueryCoordinator:
        def __init__(self):
            self._condition = asyncio.Condition()
            self._active = None
            self._waiting = []
            self._max_waiting = max(1, int(os.getenv("RK_QUERY_MAX_QUEUE", "5")))

        async def acquire(self, question: str, mode: str, client_token: str | None = None):
            lease = {
                "request_id": f"query-{uuid4().hex[:12]}", "question": question,
                "mode": mode, "client_token": client_token,
                "enqueued_at": datetime.now(timezone.utc).isoformat(),
            }
            async with self._condition:
                if len(self._waiting) >= self._max_waiting:
                    return None, self._snapshot_unlocked(client_token)
                self._waiting.append(lease)
                try:
                    while self._active is not None or self._waiting[0] is not lease:
                        await self._condition.wait()
                    self._waiting.pop(0)
                    lease["started_at"] = datetime.now(timezone.utc).isoformat()
                    self._active = lease
                    return dict(lease), None
                except BaseException:
                    if lease in self._waiting:
                        self._waiting.remove(lease)
                        self._condition.notify_all()
                    raise

        async def release(self, request_id: str):
            async with self._condition:
                if self._active is None or self._active["request_id"] != request_id:
                    return
                self._active = None
                self._condition.notify_all()

        def _snapshot_unlocked(self, client_token: str | None = None):
            result = {"busy": self._active is not None, "queue_length": len(self._waiting), "max_queue_length": self._max_waiting}
            if client_token:
                if self._active and self._active.get("client_token") == client_token:
                    result["client"] = {"state": "running", "position": 0}
                else:
                    for index, item in enumerate(self._waiting):
                        if item.get("client_token") == client_token:
                            result["client"] = {"state": "queued", "position": index + 1}
                            break
            return result

        async def snapshot(self, client_token: str | None = None):
            async with self._condition:
                return self._snapshot_unlocked(client_token)

'''


def install(path: Path) -> None:
    source = path.read_text()
    if V3 in source:
        print(f"already installed: {path}")
        return
    if V2 not in source:
        raise SystemExit("expected FIFO gate V2 before installing queue progress")
    source = source.replace(
        "from fastapi import APIRouter, Depends, HTTPException",
        "from fastapi import APIRouter, Depends, HTTPException, Request",
        1,
    )
    source, count = re.subn(
        r"    # RK3588_QUERY_FIFO_GATE_V2\n.*?(?=    query_coordinator = QueryCoordinator\(\)\n)",
        COORDINATOR,
        source,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise SystemExit("unable to replace FIFO coordinator")
    source = source.replace(
        "async def query_status():\n        \"\"\"Return the one globally active question without exposing client identity.\"\"\"\n        return await query_coordinator.snapshot()",
        "async def query_status(http_request: Request):\n        \"\"\"Return only aggregate queue state plus this browser's token state.\"\"\"\n        return await query_coordinator.snapshot(http_request.headers.get(\"x-rk-queue-token\"))",
        1,
    )
    source = source.replace("async def query_text(request: QueryRequest):", "async def query_text(request: QueryRequest, http_request: Request):", 1)
    source = source.replace("async def query_text_stream(request: QueryRequest):", "async def query_text_stream(request: QueryRequest, http_request: Request):", 1)
    source = source.replace(
        "query_coordinator.acquire(request.query, request.mode)",
        "query_coordinator.acquire(request.query, request.mode, http_request.headers.get(\"x-rk-queue-token\"))",
    )
    if "query_coordinator.acquire(request.query, request.mode)" in source:
        raise SystemExit("unable to upgrade acquire calls")
    path.write_text(source)
    print(f"installed queue progress: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("query_routes", type=Path)
    install(parser.parse_args().query_routes)
