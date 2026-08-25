#!/usr/bin/env python3
"""Local HTTP facade for the resident RK1828 JSONL model workers.

The gateway owns one child process per configured model and serializes requests
per child.  Model initialization therefore happens once when this process
starts, never once per LightRAG request.
"""

from __future__ import annotations

import json
import math
import os
import shlex
import subprocess
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class JsonlWorker:
    def __init__(self, name: str, command: str) -> None:
        self.name = name
        self.command = shlex.split(command)
        self.process: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1,
        )
        deadline = time.monotonic() + float(os.getenv("RK_GATEWAY_STARTUP_TIMEOUT", "180"))
        while time.monotonic() < deadline:
            line = self.process.stdout.readline()
            if not line:
                if self.process.poll() is not None:
                    raise RuntimeError(f"{self.name} exited during startup: {self.process.returncode}")
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue  # SDK diagnostics before the daemon's ready event.
            if payload.get("ready") is True:
                return
        raise TimeoutError(f"{self.name} did not emit ready before startup timeout")

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.start()
            assert self.process and self.process.stdin and self.process.stdout
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            while True:
                line = self.process.stdout.readline()
                if not line:
                    raise RuntimeError(f"{self.name} stopped while serving a request")
                try:
                    reply = json.loads(line)
                except json.JSONDecodeError:
                    continue  # Ignore SDK diagnostic lines emitted to stdout.
                if "ok" in reply:
                    if not reply["ok"]:
                        raise RuntimeError(reply.get("error", f"{self.name} request failed"))
                    return reply

    def request_stream(self, payload: dict[str, Any], on_delta) -> dict[str, Any]:
        """Forward daemon JSONL deltas and always drain one complete request.

        A browser can disconnect while an RK1828 generation is still running.
        The daemon itself cannot cancel that generation, so abandoning its
        JSONL output here would leave deltas/final status on stdout.  The next
        request would then consume that stale output and appear to answer the
        wrong question.  After a downstream write failure we therefore stop
        forwarding but keep draining through the matching final ``ok`` record.
        """
        with self.lock:
            self.start()
            assert self.process and self.process.stdin and self.process.stdout
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            downstream_open = True
            while True:
                line = self.process.stdout.readline()
                if not line:
                    raise RuntimeError(f"{self.name} stopped while serving a request")
                try:
                    reply = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if reply.get("event") == "delta":
                    if downstream_open:
                        try:
                            on_delta(str(reply.get("text", "")))
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            # The HTTP client has gone away. Keep consuming this
                            # daemon response so no stale event contaminates the
                            # next request handled by this resident worker.
                            downstream_open = False
                    continue
                if "ok" in reply:
                    if not reply["ok"]:
                        raise RuntimeError(reply.get("error", f"{self.name} request failed"))
                    return reply

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


def worker_from_env(name: str, env_name: str) -> JsonlWorker | None:
    command = os.getenv(env_name, "").strip()
    return JsonlWorker(name, command) if command else None


class Gateway:
    def __init__(self) -> None:
        self.llm = worker_from_env("llm", "RK_LLM_COMMAND")
        self.embedding = worker_from_env("embedding", "RK_EMBEDDING_COMMAND")
        self.reranker = worker_from_env("reranker", "RK_RERANKER_COMMAND")

    def health(self) -> dict[str, Any]:
        def state(worker: JsonlWorker | None) -> str:
            if worker is None:
                return "disabled"
            return "ready" if worker.process and worker.process.poll() is None else "not_started"

        return {"ok": True, "llm": state(self.llm), "embedding": state(self.embedding), "reranker": state(self.reranker)}

    def warmup(self) -> None:
        """Start resident workers during service boot, never on a user query.

        LLM initialization is intentionally eager by default.  Embedding and
        reranker remain lazy because they share the third accelerator and are
        not required for the WebUI to become interactive. Set
        ``RK_GATEWAY_EAGER_WORKERS=llm,embedding,reranker`` only when the
        board deployment reserves sufficient independent resources for all.
        """
        requested = {
            value.strip().lower()
            for value in os.getenv("RK_GATEWAY_EAGER_WORKERS", "llm").split(",")
            if value.strip()
        }
        for name, worker in (("llm", self.llm), ("embedding", self.embedding), ("reranker", self.reranker)):
            if name in requested and worker is not None:
                worker.start()


GATEWAY = Gateway()


class Handler(BaseHTTPRequestHandler):
    server_version = "RK1828ModelGateway/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("gateway: " + fmt % args + "\n")

    def send_json(self, code: HTTPStatus, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def begin_chat_stream(self, *, model: str):
        """Open an OpenAI-compatible SSE response and return a delta writer."""
        completion_id = "chatcmpl-" + str(uuid.uuid4())
        created = int(time.time())
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def event(body: dict[str, Any]) -> None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.wfile.write(b"data: " + payload + b"\n\n")
            self.wfile.flush()

        def delta(text: str) -> None:
            if text:
                event({
                    "id": completion_id, "object": "chat.completion.chunk",
                    "created": created, "model": model,
                    "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                })

        def finish() -> None:
            event({
            "id": completion_id, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            })
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True

        return delta, finish

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(HTTPStatus.OK, GATEWAY.health())
        elif self.path == "/v1/models":
            data = []
            if GATEWAY.llm: data.append({"id": "qwen3.5-9b-110k", "object": "model"})
            if GATEWAY.embedding: data.append({"id": "qwen3-embedding-0.6b", "object": "model"})
            if GATEWAY.reranker: data.append({"id": "qwen3-reranker-0.6b", "object": "model"})
            self.send_json(HTTPStatus.OK, {"object": "list", "data": data})
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        try:
            request = self.read_json()
            if self.path == "/v1/chat/completions":
                if not GATEWAY.llm: raise RuntimeError("LLM worker is disabled")
                configured_max_tokens = int(os.environ.get("RK_LLM_DEFAULT_MAX_TOKENS", "1536"))
                requested_max_tokens = int(
                    request.get("max_tokens", request.get("max_new_tokens", configured_max_tokens))
                )
                # LightRAG clients may send a conservative max_tokens value.
                # Keep a board-wide floor so multi-section Chinese answers are
                # not cut off midway by that client default.
                max_new_tokens = max(requested_max_tokens, configured_max_tokens)
                print(
                    f"gateway: chat requested_max_tokens={requested_max_tokens} "
                    f"resolved_max_new_tokens={max_new_tokens}",
                    file=sys.stderr,
                    flush=True,
                )
                worker_request = {
                    "id": request.get("id", str(uuid.uuid4())),
                    "messages": request["messages"],
                    "max_new_tokens": max_new_tokens,
                    "enable_thinking": bool(request.get("enable_thinking", False)),
                }
                model = request.get("model", "qwen3.5-9b-110k")
                if request.get("stream", False):
                    write_delta, finish_stream = self.begin_chat_stream(model=model)
                    try:
                        GATEWAY.llm.request_stream(worker_request, write_delta)
                    finally:
                        # A disconnected browser may also reject the final SSE
                        # marker. The daemon response was already drained above.
                        try:
                            finish_stream()
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            pass
                    return
                reply = GATEWAY.llm.request(worker_request)
                metrics = reply.get("metrics", {})
                usage = {
                    "prompt_tokens": int(metrics.get("input_tokens", 0)),
                    "completion_tokens": int(metrics.get("output_tokens", 0)),
                    "total_tokens": int(metrics.get("total_tokens", 0)),
                }
                # Metrics remain in the HTTP response.  Do not synchronously
                # log each request during performance benchmarks.
                self.send_json(HTTPStatus.OK, {
                    "id": "chatcmpl-" + str(uuid.uuid4()), "object": "chat.completion",
                    "created": int(time.time()), "model": model,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": reply["text"]}, "finish_reason": "stop"}],
                    "usage": usage,
                    "rk_metrics": metrics,
                })
                return
            if self.path == "/v1/embeddings":
                if not GATEWAY.embedding: raise RuntimeError("embedding worker is disabled")
                reply = GATEWAY.embedding.request({"id": str(uuid.uuid4()), "input": request["input"]})
                # Rockchip's Qwen3 embedding exporter exposes the final hidden
                # state directly. Qwen's retrieval recipe L2-normalizes it
                # before cosine search; perform that missing postprocess here.
                vectors = []
                for vector in reply["data"]:
                    norm = math.sqrt(sum(value * value for value in vector))
                    vectors.append([value / norm for value in vector] if norm else vector)
                self.send_json(HTTPStatus.OK, {
                    "object": "list", "model": request.get("model", "qwen3-embedding-0.6b"),
                    "data": [{"object": "embedding", "index": i, "embedding": vector}
                             for i, vector in enumerate(vectors)],
                })
                return
            if self.path == "/v1/rerank":
                if not GATEWAY.reranker: raise RuntimeError("reranker worker is disabled")
                documents = request["documents"]
                worker_request = {"id": str(uuid.uuid4()), "query": request["query"], "documents": documents}
                if request.get("instruction"):
                    worker_request["instruction"] = request["instruction"]
                reply = GATEWAY.reranker.request(worker_request)
                pairs = sorted(enumerate(reply["scores"]), key=lambda item: item[1], reverse=True)
                self.send_json(HTTPStatus.OK, {"results": [
                    {"index": index, "relevance_score": score, "document": documents[index]}
                    for index, score in pairs
                ]})
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "not found"}})
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": {"message": str(exc)}})


def main() -> None:
    address = (os.getenv("RK_GATEWAY_HOST", "127.0.0.1"), int(os.getenv("RK_GATEWAY_PORT", "8100")))
    GATEWAY.warmup()
    print(f"RK1828 model gateway listening at http://{address[0]}:{address[1]}", flush=True)
    try:
        ThreadingHTTPServer(address, Handler).serve_forever()
    finally:
        for worker in (GATEWAY.llm, GATEWAY.embedding, GATEWAY.reranker):
            if worker: worker.stop()


if __name__ == "__main__":
    main()
