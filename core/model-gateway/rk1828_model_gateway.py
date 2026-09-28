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
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen


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


class RkllmHttpWorker:
    """Manage the vendor rkllm3-server and adapt its OpenAI API internally."""

    def __init__(self, name: str, command: str, base_url: str, model: str) -> None:
        self.name = name
        self.command = shlex.split(command)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.process: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()

    def _open(self, path: str, payload: dict[str, Any] | None = None, *, timeout: float):
        body = None
        headers: dict[str, str] = {}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, data=body, headers=headers)
        try:
            return urlopen(request, timeout=timeout)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{self.name} HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"{self.name} request failed: {exc.reason}") from exc

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return
        self.process = subprocess.Popen(
            self.command,
            stdout=sys.stderr,
            stderr=sys.stderr,
            text=True,
        )
        deadline = time.monotonic() + float(
            os.getenv("RK_GATEWAY_STARTUP_TIMEOUT", "180")
        )
        last_error = "server did not answer"
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"{self.name} exited during startup: {self.process.returncode}"
                )
            try:
                with self._open("/health", timeout=2) as response:
                    if response.status == HTTPStatus.OK:
                        # A previous orphan may still own the configured port.
                        # Give this child a moment to fail its bind and only
                        # accept health when the process we spawned stays alive.
                        time.sleep(0.25)
                        if self.process.poll() is not None:
                            raise RuntimeError(
                                f"{self.name} exited during startup: "
                                f"{self.process.returncode}"
                            )
                        return
            except RuntimeError as exc:
                last_error = str(exc)
            time.sleep(0.25)
        self.stop()
        raise TimeoutError(f"{self.name} did not become healthy: {last_error}")

    def _chat_payload(
        self, payload: dict[str, Any], *, stream: bool
    ) -> dict[str, Any]:
        max_new_tokens = max(1, int(payload.get("max_new_tokens", 512)))
        enable_thinking = bool(payload.get("enable_thinking", False))
        messages = payload["messages"]
        system_parts = [
            str(message.get("content", "")).strip()
            for message in messages
            if message.get("role") == "system" and message.get("content")
        ]
        non_system_messages = [
            message for message in messages if message.get("role") != "system"
        ]
        # Qwen3.5's bundled Jinja template rejects a second system message.
        # LightRAG intentionally supplies a grounding contract plus its own
        # RAG role prompt, so preserve both by folding them into one first turn.
        normalized_messages = non_system_messages
        if system_parts:
            normalized_messages = [
                {"role": "system", "content": "\n\n".join(system_parts)}
            ] + non_system_messages
        return {
            # LightRAG uses logical aliases such as ``*-query`` to select a
            # task policy. rkllm3-server exposes only the alias it loaded at
            # startup, so translate every logical gateway model to that one
            # physical model id before forwarding.
            "model": self.model,
            "messages": normalized_messages,
            "stream": stream,
            # rkllm3-server accepts the standard field and exposes n_predict
            # as its request-level override. Send both so the actual native
            # decode ceiling always follows the gateway's resolved budget.
            "max_tokens": max_new_tokens,
            "n_predict": max_new_tokens,
            "cache_prompt": False,
            "id_slot": 0,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
            **({"stream_options": {"include_usage": True}} if stream else {}),
        }

    @staticmethod
    def _metrics(response: dict[str, Any]) -> dict[str, Any]:
        usage = response.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        output_tokens = int(usage.get("completion_tokens", 0))
        return {
            "input_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(
                usage.get("total_tokens", prompt_tokens + output_tokens)
            ),
        }

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.start()
            request_timeout = float(os.getenv("RK_LLM_HTTP_TIMEOUT", "600"))
            with self._open(
                "/v1/chat/completions",
                self._chat_payload(payload, stream=False),
                timeout=request_timeout,
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
            choice = body["choices"][0]
            return {
                "ok": True,
                "text": str(choice.get("message", {}).get("content") or ""),
                "finish_reason": str(choice.get("finish_reason") or "stop"),
                "metrics": self._metrics(body),
            }

    def request_stream(self, payload: dict[str, Any], on_delta) -> dict[str, Any]:
        with self.lock:
            self.start()
            request_timeout = float(os.getenv("RK_LLM_HTTP_TIMEOUT", "600"))
            finish_reason = "stop"
            downstream_open = True
            metrics = {}
            with self._open(
                "/v1/chat/completions",
                self._chat_payload(payload, stream=True),
                timeout=request_timeout,
            ) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    chunk = json.loads(data)
                    if chunk.get("usage"):
                        metrics = self._metrics(chunk)
                        timings = chunk.get("timings") or {}
                        for key in ("prompt_ms", "predicted_ms", "predicted_per_second"):
                            if key in timings:
                                metrics[key] = timings[key]
                    choice = (chunk.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    text = str(delta.get("content") or "")
                    if text and downstream_open:
                        try:
                            on_delta(text)
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            downstream_open = False
                    if choice.get("finish_reason"):
                        finish_reason = str(choice["finish_reason"])
            return {"ok": True, "finish_reason": finish_reason, "metrics": metrics}

    def stop(self) -> None:
        if not self.process or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def worker_from_env(name: str, env_name: str) -> JsonlWorker | None:
    command = os.getenv(env_name, "").strip()
    return JsonlWorker(name, command) if command else None


def llm_worker_from_env():
    server_command = os.getenv("RK_LLM_SERVER_COMMAND", "").strip()
    if server_command:
        return RkllmHttpWorker(
            "llm",
            server_command,
            os.getenv("RK_LLM_SERVER_URL", "http://127.0.0.1:8080"),
            os.getenv("RK_LLM_MODEL", "qwen3.5-4b"),
        )
    return worker_from_env("llm", "RK_LLM_COMMAND")


def ingest_llm_worker_from_env():
    server_command = os.getenv("RK_INGEST_LLM_SERVER_COMMAND", "").strip()
    if server_command:
        return RkllmHttpWorker(
            "ingest_llm",
            server_command,
            os.getenv("RK_INGEST_LLM_SERVER_URL", "http://127.0.0.1:8080"),
            os.getenv("RK_INGEST_LLM_MODEL", "qwen3.5-4b"),
        )
    return worker_from_env("ingest_llm", "RK_INGEST_LLM_COMMAND")


class Gateway:
    def __init__(self) -> None:
        self.query_llm = llm_worker_from_env()
        self.ingest_llm = ingest_llm_worker_from_env()
        self.llm = self.query_llm
        self.embedding = worker_from_env("embedding", "RK_EMBEDDING_COMMAND")
        self.reranker = worker_from_env("reranker", "RK_RERANKER_COMMAND")
        self.single_device = os.getenv("RK_GATEWAY_SINGLE_DEVICE", "0").strip().lower() in {
            "1", "true", "yes", "on",
        }
        # JsonlWorker locks serialize requests only within one child process.
        # Vector models always share a card, so they use one cross-worker lock.
        # In single-device mode the LLM joins that same lock, preventing NPU
        # execution and lazy model initialization from overlapping on the card.
        self.vector_lock = threading.Lock()
        self.ingest_mode_enabled = os.getenv(
            "RK_GATEWAY_INGEST_MODE_ENABLED", "0"
        ).strip().lower() in {"1", "true", "yes", "on"}
        exclusive_value = os.getenv(
            "RK_GATEWAY_LLM_EXCLUSIVE",
            os.getenv("RK_GATEWAY_FINAL_QUERY_EXCLUSIVE", "0"),
        )
        self.llm_exclusive = exclusive_value.strip().lower() in {
            "1", "true", "yes", "on",
        }
        self.llm_stop_workers = {
            value.strip().lower()
            for value in os.getenv(
                "RK_GATEWAY_LLM_STOP_WORKERS", "embedding,reranker"
            ).split(",")
            if value.strip()
        }
        self.mode_condition = threading.Condition()
        self.ingest_mode = False
        self.model_stop_settle_seconds = float(
            os.getenv("RK_GATEWAY_MODEL_STOP_SETTLE_SECONDS", "0")
        )

    def settle_after_model_stop(self) -> None:
        """Allow device-side allocations to disappear after daemon exit."""
        if self.model_stop_settle_seconds > 0:
            time.sleep(self.model_stop_settle_seconds)

    def request_llm(self, payload: dict[str, Any]) -> dict[str, Any]:
        assert self.llm is not None
        if self.single_device and self.llm_exclusive:
            return self._request_exclusive_llm(lambda: self.llm.request(payload))
        if self.single_device:
            with self.vector_lock:
                return self.llm.request(payload)
        return self.llm.request(payload)

    def request_llm_stream(self, payload: dict[str, Any], on_delta) -> dict[str, Any]:
        assert self.llm is not None
        if self.single_device and self.llm_exclusive:
            return self._request_exclusive_llm(
                lambda: self.llm.request_stream(payload, on_delta)
            )
        if self.single_device:
            with self.vector_lock:
                return self.llm.request_stream(payload, on_delta)
        return self.llm.request_stream(payload, on_delta)

    def request_aux_llm(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run extraction/keyword generation without deadlocking ingest mode.

        Query-time auxiliary calls retain the normal exclusive-LLM policy.
        During document ingestion, however, the reranker has already been
        released and the pipeline itself owns the ingest phase.  Waiting for
        that phase to end here creates a cycle: ingestion waits for extraction
        while extraction waits for ingestion.  Serialize directly on the card
        lock in that case and leave the resident embedding worker untouched.
        """
        assert self.llm is not None
        with self.mode_condition:
            ingest_mode = self.ingest_mode
        if ingest_mode and self.single_device:
            with self.vector_lock:
                return self.llm.request(payload)
        return self.request_llm(payload)

    def request_aux_llm_stream(
        self, payload: dict[str, Any], on_delta
    ) -> dict[str, Any]:
        assert self.llm is not None
        with self.mode_condition:
            ingest_mode = self.ingest_mode
        if ingest_mode and self.single_device:
            with self.vector_lock:
                return self.llm.request_stream(payload, on_delta)
        return self.request_llm_stream(payload, on_delta)

    def _request_exclusive_llm(self, request_fn) -> dict[str, Any]:
        """Run one LLM generation with vector-model memory released.

        All three models remain resident while idle and during retrieval.  The
        5 GB card does not, however, retain enough contiguous runtime memory to
        guarantee repeated 4B generation with both vector workers resident.
        Serialize the phase transition, stop the vector workers only for final
        answer generation, and restore them before accepting the next query.
        """
        if not (self.single_device and self.llm_exclusive):
            return request_fn()
        with self.mode_condition:
            while self.ingest_mode:
                self.mode_condition.wait()
        with self.vector_lock:
            try:
                if self.embedding is not None and "embedding" in self.llm_stop_workers:
                    self.embedding.stop()
                if self.reranker is not None and "reranker" in self.llm_stop_workers:
                    self.reranker.stop()
                self.settle_after_model_stop()
                return request_fn()
            finally:
                # Reranker has the larger initialization peak; preserve the
                # established safe restore order used after ingestion.
                if self.reranker is not None and "reranker" in self.llm_stop_workers:
                    self.reranker.start()
                if self.embedding is not None and "embedding" in self.llm_stop_workers:
                    self.embedding.start()

    def request_final_query_llm(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.mode_condition:
            while self.ingest_mode:
                self.mode_condition.wait()
        return self.request_llm(payload)

    def request_final_query_llm_stream(
        self, payload: dict[str, Any], on_delta
    ) -> dict[str, Any]:
        with self.mode_condition:
            while self.ingest_mode:
                self.mode_condition.wait()
        return self.request_llm_stream(payload, on_delta)

    def request_vector(self, worker: JsonlWorker, payload: dict[str, Any]) -> dict[str, Any]:
        with self.vector_lock:
            return worker.request(payload)

    def request_reranker(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Wait for query mode before using the temporarily unloaded reranker."""
        assert self.reranker is not None
        with self.mode_condition:
            while self.ingest_mode:
                self.mode_condition.wait()
        return self.request_vector(self.reranker, payload)

    def enter_ingest_mode(self) -> dict[str, Any]:
        """Switch once from the query model to the ingestion model."""
        if not self.ingest_mode_enabled:
            raise RuntimeError("ingest model mode is disabled")
        with self.mode_condition:
            if self.ingest_mode:
                return self.health()
            # Publish the mode before waiting for an in-flight device request.
            # New rerank requests now wait instead of lazily restarting the
            # worker after it has been stopped.
            self.ingest_mode = True
        try:
            with self.vector_lock:
                if self.reranker is not None:
                    self.reranker.stop()
                if self.ingest_llm is not None:
                    # Start the larger ingestion model from a clean allocator.
                    # Embedding remains available lazily when vector writes
                    # begin later in the same ingestion run.
                    if self.embedding is not None:
                        self.embedding.stop()
                    if self.llm is not None:
                        self.llm.stop()
                    self.settle_after_model_stop()
                    self.llm = self.ingest_llm
                    self.llm.start()
                else:
                    self.settle_after_model_stop()
        except BaseException:
            if self.ingest_llm is not None:
                self.ingest_llm.stop()
                self.llm = self.query_llm
                if self.query_llm is not None:
                    self.query_llm.start()
                if self.reranker is not None:
                    self.reranker.start()
                if self.embedding is not None:
                    self.embedding.start()
            with self.mode_condition:
                self.ingest_mode = False
                self.mode_condition.notify_all()
            raise
        return self.health()

    def leave_ingest_mode(self) -> dict[str, Any]:
        """Restore the memory-safe 2B -> reranker -> embedding query layout."""
        if not self.ingest_mode_enabled:
            raise RuntimeError("ingest model mode is disabled")
        with self.mode_condition:
            if not self.ingest_mode:
                return self.health()
        # Reranker has the larger initialization peak and cannot reliably start
        # after embedding on the 5 GB card. Recreate the two vector workers in
        # their known-good order while all device work remains serialized.
        try:
            with self.vector_lock:
                if self.embedding is not None:
                    self.embedding.stop()
                if self.ingest_llm is not None:
                    self.ingest_llm.stop()
                    self.settle_after_model_stop()
                    self.llm = self.query_llm
                    if self.llm is not None:
                        self.llm.start()
                else:
                    self.settle_after_model_stop()
                if self.reranker is not None:
                    self.reranker.start()
                if self.embedding is not None:
                    self.embedding.start()
        finally:
            with self.mode_condition:
                self.ingest_mode = False
                self.mode_condition.notify_all()
        return self.health()

    def health(self) -> dict[str, Any]:
        def state(worker: JsonlWorker | None) -> str:
            if worker is None:
                return "disabled"
            return "ready" if worker.process and worker.process.poll() is None else "not_started"

        return {
            "ok": True,
            "mode": "ingest" if self.ingest_mode else "query",
            "llm_role": (
                "ingest"
                if self.ingest_llm is not None and self.llm is self.ingest_llm
                else "query"
            ),
            "llm": state(self.llm),
            "embedding": state(self.embedding),
            "reranker": state(self.reranker),
        }

    def warmup(self) -> None:
        """Start resident workers during service boot, never on a user query.

        LLM initialization is intentionally eager by default.  Embedding and
        reranker remain lazy because they share an accelerator and are
        not required for the WebUI to become interactive. Set
        ``RK_GATEWAY_EAGER_WORKERS=llm,embedding,reranker`` only when the
        models are assigned to independent accelerators.
        """
        requested = {
            value.strip().lower()
            for value in os.getenv("RK_GATEWAY_EAGER_WORKERS", "llm").split(",")
            if value.strip()
        }
        workers = [("llm", self.llm), ("embedding", self.embedding), ("reranker", self.reranker)]
        if self.single_device:
            # Reranker has the larger initialization peak. Starting it before
            # embedding lets all three workers become resident on a 5 GB card;
            # the reverse order can make reranker exit during initialization.
            workers = [("llm", self.llm), ("reranker", self.reranker), ("embedding", self.embedding)]
        for name, worker in workers:
            if name in requested and worker is not None:
                worker.start()


GATEWAY = Gateway()
CHAT_METRICS_LOCK = threading.Lock()
CHAT_METRICS = deque(maxlen=512)
CHAT_METRICS_SEQUENCE = 0


def record_chat_metrics(model: str, metrics: dict[str, Any], *, stream: bool,
                        elapsed_ms: float, finish_reason: str, source: str = "native") -> None:
    """Keep prompt-free usage records for a local, sequential Q&A benchmark."""
    global CHAT_METRICS_SEQUENCE
    with CHAT_METRICS_LOCK:
        CHAT_METRICS_SEQUENCE += 1
        CHAT_METRICS.append({
            "sequence": CHAT_METRICS_SEQUENCE,
            "kind": "llm",
            "model": model,
            "stream": stream,
            "source": source,
            "input_tokens": metrics.get("input_tokens"),
            "output_tokens": metrics.get("output_tokens"),
            "total_tokens": metrics.get("total_tokens"),
            "prompt_ms": metrics.get("prompt_ms"),
            "predicted_ms": metrics.get("predicted_ms"),
            "decode_tps": metrics.get("predicted_per_second"),
            "elapsed_ms": round(elapsed_ms, 1),
            "finish_reason": finish_reason,
        })


def record_vector_metrics(kind: str, *, elapsed_ms: float,
                          input_items: int | None = None,
                          input_chars: int | None = None,
                          candidate_count: int | None = None,
                          query_chars: int | None = None,
                          vector_dimensions: int | None = None,
                          input_tokens: int | None = None,
                          tokens_per_item: list[int] | None = None) -> None:
    """Record vector request cost without retaining query or document text."""
    global CHAT_METRICS_SEQUENCE
    with CHAT_METRICS_LOCK:
        CHAT_METRICS_SEQUENCE += 1
        CHAT_METRICS.append({
            "sequence": CHAT_METRICS_SEQUENCE,
            "kind": kind,
            "elapsed_ms": round(elapsed_ms, 1),
            "input_items": input_items,
            "input_chars": input_chars,
            "candidate_count": candidate_count,
            "query_chars": query_chars,
            "vector_dimensions": vector_dimensions,
            "input_tokens": input_tokens,
            "tokens_per_item": tokens_per_item,
            "input_tps": (
                round(input_tokens * 1000 / elapsed_ms, 2)
                if input_tokens is not None and elapsed_ms > 0 else None
            ),
            "token_note": (
                "native_prefill_tokens"
                if input_tokens is not None
                else "native_vector_daemon_does_not_return_token_count"
            ),
        })


def chat_metrics_after(after: int) -> dict[str, Any]:
    with CHAT_METRICS_LOCK:
        return {
            "latest_sequence": CHAT_METRICS_SEQUENCE,
            "records": [item for item in CHAT_METRICS if item["sequence"] > after],
        }


LLM_MODEL_ID = os.getenv("RK_LLM_MODEL", "qwen3.5-9b-110k")
QUERY_MODEL_ID = os.getenv("RK_QUERY_MODEL", LLM_MODEL_ID)
QUERY_MAX_TOKENS = int(os.getenv("RK_QUERY_MAX_TOKENS", "128"))
LLM_CONTEXT_TOKENS = int(os.getenv("RK_LLM_CONTEXT_TOKENS", "4096"))
QUERY_CONTEXT_RESERVE = int(os.getenv("RK_QUERY_CONTEXT_RESERVE", "128"))
QUERY_SYSTEM_PROMPT = (
    "只依据检索上下文回答，不用常识补全。名称、数值、命令、路径和动作词按原文抄写。"
    "“仅X”事实只能归入X；比较对象的事实只能取自该对象标题至下一个同级标题之间。"
    "一般规则与特定例外并存时写明例外。询问当前设备而上下文无实时证据时，只说无法确认及需检查项。"
    "答案只写一遍；禁止总结、背景、无关参数、思考过程和自行生成 References 或引用列表。"
)
QUERY_OUTPUT_SUFFIX = (
    "\n\n直接回答且只写一次。不得漏掉问题点名的对象，不得跨标题取值；"
    "不要输出总结、背景、References 或引用列表，引用由系统统一追加。"
)


def extract_user_query(prompt_content: str) -> str:
    """Extract LightRAG's final user query from its assembled prompt."""
    marker = "---User Query---"
    return prompt_content.rsplit(marker, 1)[-1].strip() if marker in prompt_content else prompt_content.strip()


def fast_metric_keywords(messages: list[dict[str, Any]]) -> str | None:
    """Return deterministic keywords for explicit model-metric questions.

    LightRAG normally spends one LLM turn extracting keywords before Mix
    retrieval. On the single 5 GB card that turn also forces an embedding
    stop/reload cycle. Exact model benchmark questions already contain their
    high-signal identifiers, so preserve those literals without invoking the
    LLM. All other keyword prompts retain the upstream extraction path.
    """
    content = "\n".join(
        str(message.get("content", ""))
        for message in messages
        if message.get("role") == "user"
    )
    if "expert keyword extractor" not in content.casefold():
        return None
    match = re.search(
        r"User Query:\s*(.*?)\s*---Output---",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    query = match.group(1).strip()
    folded = query.casefold()
    if not any(
        term in folded
        for term in ("性能", "performance", "ttft", "tpot", "tps", "吞吐", "延迟")
    ):
        return None

    identifiers: list[str] = []
    for pattern in (
        r"[A-Za-z][A-Za-z0-9]*(?:[._+-][A-Za-z0-9]+)+",
        r"RK\d{4}[A-Za-z0-9]*",
    ):
        for value in re.findall(pattern, query, flags=re.IGNORECASE):
            if value.casefold() not in {item.casefold() for item in identifiers}:
                identifiers.append(value)
    if not identifiers:
        return None

    metric_labels = []
    for literal, canonical in (
        ("input tokens", "Input Tokens"),
        ("new tokens", "New Tokens"),
        ("ttft", "TTFT"),
        ("tpot", "TPOT"),
        ("decode tps", "Decode TPS"),
        ("tps", "TPS"),
    ):
        if literal in folded and canonical not in metric_labels:
            metric_labels.append(canonical)
    low_level = identifiers + metric_labels
    return json.dumps(
        {
            "high_level_keywords": ["model performance", "inference metrics"],
            "low_level_keywords": low_level,
        },
        ensure_ascii=False,
    )


def intent_output_suffix(query: str) -> str:
    """Return one high-priority format contract instead of competing rules."""
    folded = query.casefold()
    if any(term in folded for term in ("当前", "现在", "这台")):
        return (
            "\n若上下文没有实时证据，只输出两句：第一句说无法从知识库确认；"
            "第二句说需检查当前设备或服务配置。禁止列历史方案、可能原因、排查步骤或具体命令。"
        )
    if "归类为什么错误" in folded or "归类为何错误" in folded:
        return "\n只输出错误类别和一条直接判据，共一句话。"
    if any(term in folded for term in ("复现", "完整部署")):
        return (
            "\n只按以下五行作答："
            "1. 环境：<关键硬件和软件>\n"
            "2. 授权：<授权输入和产物>\n"
            "3. 部署：<脚本和目标目录>\n"
            "4. 模型：<模型目录>\n"
            "5. 启动验证：<原文启动命令及验证方式>\n"
            "每个尖括号只填一个短语；不得加标题、解释或第六行。"
        )
    if any(term in folded for term in ("为什么", "原因")):
        return (
            "\n只列上下文直接证明的原因，共一至三条；"
            "不为凑数添加第三条，列完立即结束。"
        )
    if "一样吗" in folded:
        return "\n只用一句话先写通则、再写特定方式的例外，不得分项或重复。"
    if any(term in folded for term in ("区别", "对比", "比较")):
        return (
            "\n每个点名对象只写一个单行列表项；仅从其标题区间取事实；"
            "写完所有对象立即结束，不得换一种说法重复。"
        )
    if any(term in folded for term in ("支持哪些", "有哪些", "哪些模式")):
        return (
            "\n直接列出上下文明确给出的项目，每项只写名称和一句必要说明；"
            "列完立即结束，不补充其他类别。"
        )
    # “性能如何” asks for a factual result, not instructions.  Return no
    # extra contract and let LightRAG's grounded answer prompt consume the
    # retrieved table.  This guard must precede the generic “如何” rule.
    if any(term in folded for term in ("性能如何", "性能怎么样", "性能是多少")):
        return ""
    if any(term in folded for term in ("命令", "怎么用", "如何通过", "怎么查看", "怎么写")):
        return "\n只输出命令代码块和一句预期结果或说明。"
    if "哪里" in folded and any(term in folded for term in ("怎么", "如何")):
        return "\n第一句回答位置，再输出最多两个不重复的定位步骤，不得自行列引用。"
    if any(term in folded for term in ("配置流程", "怎么配置", "如何配置")):
        return (
            "\n只输出上下文能够直接证明的三至五个必要操作步骤，每步一句，写完立即结束；"
            "只覆盖上下文明确给出的入口、创建或编辑动作及必要参数；"
            "删除操作不算配置步骤，参数选项只能写成设置内容，不得编造成按钮或重复执行创建动作；"
            "不得补写上下文未出现的保存、验证或退出操作，不展开全部可选参数，不得自行列引用。"
        )
    if any(term in folded for term in ("怎么", "如何")):
        return "\n只输出一至三个不重复的操作步骤，不得自行列引用。"
    return ""


def prepare_query_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add the small-model grounding contract without mutating caller data."""
    prepared = [dict(message) for message in messages]
    for message in reversed(prepared):
        if message.get("role") == "user":
            content = str(message.get("content", ""))
            query = extract_user_query(content)
            message["content"] = content + QUERY_OUTPUT_SUFFIX + intent_output_suffix(query)
            break
    return [{"role": "system", "content": QUERY_SYSTEM_PROMPT}] + prepared


def estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
    """Conservatively estimate Qwen prompt tokens without loading a tokenizer.

    Chinese text is close to one token per character, while long ASCII runs
    usually encode more compactly. The per-message allowance covers chat
    template markers. This is used only to keep generation inside the model's
    context window; the runtime still performs authoritative tokenization.
    """
    total = 8
    for message in messages:
        content = str(message.get("content", ""))
        non_ascii = sum(1 for char in content if ord(char) > 127)
        ascii_chars = len(content) - non_ascii
        total += non_ascii + (ascii_chars + 3) // 4 + 12
    return total


def resolve_query_max_tokens(
    messages: list[dict[str, Any]], requested: int, configured: int
) -> int:
    """Use the remaining context window instead of one fixed query length."""
    remaining = LLM_CONTEXT_TOKENS - estimate_message_tokens(messages) - QUERY_CONTEXT_RESERVE
    return min(max(requested, 1), configured, max(1, remaining))


_MODEL_REFERENCE_HEADING_RE = re.compile(
    r"(?:^|\n)\s*(?:#{1,6}\s*)?(?:\*{1,2})?\s*"
    r"(?:references|参考(?:文献|依据)|引用)\s*(?:\*{1,2})?\s*[:：]?\s*(?:\n|$)",
    flags=re.IGNORECASE,
)


def strip_model_reference_footer(text: str) -> str:
    """Remove an LLM-authored citation footer; LightRAG appends the trusted one."""
    match = _MODEL_REFERENCE_HEADING_RE.search(text)
    return text[: match.start()].rstrip() if match else text


class ModelReferenceFooterFilter:
    """Incrementally suppress model-authored citation footers during streaming."""

    _TAIL_CHARS = 24

    def __init__(self, emit: Callable[[str], None]):
        self.emit = emit
        self.buffer = ""
        self.suppressed = False

    def feed(self, text: str) -> None:
        if not text or self.suppressed:
            return
        self.buffer += text
        match = _MODEL_REFERENCE_HEADING_RE.search(self.buffer)
        if match:
            prefix = self.buffer[: match.start()].rstrip()
            if prefix:
                self.emit(prefix)
            self.buffer = ""
            self.suppressed = True
            return
        if len(self.buffer) > self._TAIL_CHARS:
            safe = self.buffer[: -self._TAIL_CHARS]
            self.buffer = self.buffer[-self._TAIL_CHARS :]
            self.emit(safe)

    def finish(self) -> None:
        if self.suppressed:
            return
        clean = strip_model_reference_footer(self.buffer)
        if clean:
            self.emit(clean)
        self.buffer = ""


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

        def finish(finish_reason: str) -> None:
            event({
            "id": completion_id, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
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
        parsed = urlsplit(self.path)
        if parsed.path == "/admin/chat-metrics":
            values = parse_qs(parsed.query)
            try:
                after = int(values.get("after", ["0"])[0])
                if after < 0:
                    raise ValueError
            except ValueError:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "after must be nonnegative"})
                return
            self.send_json(HTTPStatus.OK, chat_metrics_after(after))
        elif self.path == "/health":
            self.send_json(HTTPStatus.OK, GATEWAY.health())
        elif self.path == "/v1/models":
            data = []
            if GATEWAY.llm: data.append({"id": LLM_MODEL_ID, "object": "model"})
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
                chat_started = time.monotonic()
                configured_max_tokens = int(os.environ.get("RK_LLM_DEFAULT_MAX_TOKENS", "512"))
                requested_max_tokens = int(request.get(
                    "max_completion_tokens",
                    request.get("max_tokens", request.get("max_new_tokens", configured_max_tokens)),
                ))
                # Enforce the board-wide output budget. This leaves room for
                # retrieved context within the 4K-token LLM session.
                model = request.get("model", LLM_MODEL_ID)
                is_query_model = model == QUERY_MODEL_ID
                messages = request["messages"]
                fast_keywords = (
                    None if is_query_model else fast_metric_keywords(messages)
                )
                if fast_keywords is not None:
                    print(
                        "gateway: fast local keyword extraction for model metrics",
                        file=sys.stderr,
                        flush=True,
                    )
                    usage = {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    }
                    self.send_json(HTTPStatus.OK, {
                        "id": "chatcmpl-" + str(uuid.uuid4()),
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "message": {"role": "assistant", "content": fast_keywords},
                            "finish_reason": "stop",
                        }],
                        "usage": usage,
                        "rk_metrics": {"fast_path": "metric_keywords"},
                    })
                    record_chat_metrics(model, {"input_tokens": 0, "output_tokens": 0,
                                                "total_tokens": 0}, stream=False,
                                        elapsed_ms=(time.monotonic() - chat_started) * 1000,
                                        finish_reason="stop", source="local_fast_path")
                    return
                if is_query_model:
                    # LightRAG's retrieval template is a large user message.
                    # Put the output contract at its end, nearest to the
                    # generation turn, rather than relying on a distant system
                    # instruction that a small model may underweight.
                    messages = prepare_query_messages(messages)
                    max_new_tokens = resolve_query_max_tokens(
                        messages,
                        requested_max_tokens,
                        min(QUERY_MAX_TOKENS, configured_max_tokens),
                    )
                else:
                    max_new_tokens = min(
                        max(requested_max_tokens, 1), configured_max_tokens
                    )
                print(
                    f"gateway: chat requested_max_tokens={requested_max_tokens} "
                    f"estimated_input_tokens={estimate_message_tokens(messages)} "
                    f"resolved_max_new_tokens={max_new_tokens} model={model}",
                    file=sys.stderr,
                    flush=True,
                )
                worker_request = {
                    "id": request.get("id", str(uuid.uuid4())),
                    "model": model,
                    "messages": messages,
                    "max_new_tokens": max_new_tokens,
                    "enable_thinking": bool(request.get("enable_thinking", False)),
                }
                if request.get("stream", False):
                    write_delta, finish_stream = self.begin_chat_stream(model=model)
                    finish_reason = "stop"
                    footer_filter = (
                        ModelReferenceFooterFilter(write_delta)
                        if is_query_model
                        else None
                    )
                    try:
                        request_stream = (
                            GATEWAY.request_final_query_llm_stream
                            if is_query_model
                            else GATEWAY.request_aux_llm_stream
                        )
                        reply = request_stream(
                            worker_request,
                            footer_filter.feed if footer_filter else write_delta,
                        )
                        if footer_filter:
                            footer_filter.finish()
                        finish_reason = str(reply.get("finish_reason", "stop"))
                        record_chat_metrics(
                            model, reply.get("metrics") or {}, stream=True,
                            elapsed_ms=(time.monotonic() - chat_started) * 1000,
                            finish_reason=finish_reason,
                        )
                        print(
                            f"gateway: chat finished model={model} finish_reason={finish_reason}",
                            file=sys.stderr,
                            flush=True,
                        )
                    finally:
                        # A disconnected browser may also reject the final SSE
                        # marker. The daemon response was already drained above.
                        try:
                            finish_stream(finish_reason)
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            pass
                    return
                request_llm = (
                    GATEWAY.request_final_query_llm
                    if is_query_model
                    else GATEWAY.request_aux_llm
                )
                reply = request_llm(worker_request)
                if is_query_model:
                    reply["text"] = strip_model_reference_footer(reply["text"])
                metrics = reply.get("metrics", {})
                record_chat_metrics(
                    model, metrics, stream=False,
                    elapsed_ms=(time.monotonic() - chat_started) * 1000,
                    finish_reason=str(reply.get("finish_reason", "stop")),
                )
                print(
                    f"gateway: chat finished model={model} "
                    f"finish_reason={reply.get('finish_reason', 'stop')} "
                    f"output_tokens={metrics.get('output_tokens', 0)}",
                    file=sys.stderr,
                    flush=True,
                )
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
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": reply["text"]}, "finish_reason": reply.get("finish_reason", "stop")}],
                    "usage": usage,
                    "rk_metrics": metrics,
                })
                return
            if self.path == "/v1/embeddings":
                if not GATEWAY.embedding: raise RuntimeError("embedding worker is disabled")
                vector_started = time.monotonic()
                inputs = request["input"]
                input_texts = [inputs] if isinstance(inputs, str) else inputs
                reply = GATEWAY.request_vector(
                    GATEWAY.embedding, {"id": str(uuid.uuid4()), "input": inputs}
                )
                # Rockchip's Qwen3 embedding exporter exposes the final hidden
                # state directly. Qwen's retrieval recipe L2-normalizes it
                # before cosine search; perform that missing postprocess here.
                vectors = []
                for vector in reply["data"]:
                    norm = math.sqrt(sum(value * value for value in vector))
                    vectors.append([value / norm for value in vector] if norm else vector)
                vector_elapsed_ms = (time.monotonic() - vector_started) * 1000
                input_tokens = reply.get("n_prefill_tokens")
                tokens_per_input = reply.get("prefill_tokens_per_input")
                record_vector_metrics(
                    "embedding", elapsed_ms=vector_elapsed_ms,
                    input_items=len(input_texts),
                    input_chars=sum(len(value) for value in input_texts),
                    vector_dimensions=len(vectors[0]) if vectors else None,
                    input_tokens=input_tokens,
                    tokens_per_item=tokens_per_input,
                )
                self.send_json(HTTPStatus.OK, {
                    "object": "list", "model": request.get("model", "qwen3-embedding-0.6b"),
                    "data": [{"object": "embedding", "index": i, "embedding": vector}
                             for i, vector in enumerate(vectors)],
                    "usage": {
                        "prompt_tokens": input_tokens,
                        "total_tokens": input_tokens,
                    },
                    "rk_metrics": {
                        "n_prefill_tokens": input_tokens,
                        "prefill_tokens_per_input": tokens_per_input,
                        "effective_input_tps": (
                            round(input_tokens * 1000 / vector_elapsed_ms, 2)
                            if input_tokens is not None and vector_elapsed_ms > 0 else None
                        ),
                    },
                })
                return
            if self.path == "/v1/rerank":
                if not GATEWAY.reranker: raise RuntimeError("reranker worker is disabled")
                rerank_started = time.monotonic()
                documents = request["documents"]
                worker_request = {"id": str(uuid.uuid4()), "query": request["query"], "documents": documents}
                if request.get("instruction"):
                    worker_request["instruction"] = request["instruction"]
                reply = GATEWAY.request_reranker(worker_request)
                pairs = sorted(enumerate(reply["scores"]), key=lambda item: item[1], reverse=True)
                vector_elapsed_ms = (time.monotonic() - rerank_started) * 1000
                input_tokens = reply.get("n_prefill_tokens")
                tokens_per_candidate = reply.get("prefill_tokens_per_candidate")
                record_vector_metrics(
                    "rerank", elapsed_ms=vector_elapsed_ms,
                    candidate_count=len(documents),
                    query_chars=len(request["query"]),
                    input_chars=sum(len(value) for value in documents),
                    input_tokens=input_tokens,
                    tokens_per_item=tokens_per_candidate,
                )
                self.send_json(HTTPStatus.OK, {
                    "results": [
                        {"index": index, "relevance_score": score, "document": documents[index]}
                        for index, score in pairs
                    ],
                    "rk_metrics": {
                        "n_prefill_tokens": input_tokens,
                        "prefill_tokens_per_candidate": tokens_per_candidate,
                        "effective_input_tps": (
                            round(input_tokens * 1000 / vector_elapsed_ms, 2)
                            if input_tokens is not None and vector_elapsed_ms > 0 else None
                        ),
                    },
                })
                return
            if self.path == "/admin/ingest/begin":
                self.send_json(HTTPStatus.OK, GATEWAY.enter_ingest_mode())
                return
            if self.path == "/admin/ingest/end":
                self.send_json(HTTPStatus.OK, GATEWAY.leave_ingest_mode())
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "not found"}})
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": {"message": str(exc)}})


def main() -> None:
    address = (os.getenv("RK_GATEWAY_HOST", "127.0.0.1"), int(os.getenv("RK_GATEWAY_PORT", "8100")))
    GATEWAY.warmup()
    print(f"RK1828 model gateway listening at http://{address[0]}:{address[1]}", flush=True)

    def stop_on_signal(_signum, _frame):
        # Convert service-manager termination into normal stack unwinding so
        # all model children, including rkllm3-server, are stopped in finally.
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_on_signal)
    try:
        ThreadingHTTPServer(address, Handler).serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for worker in (GATEWAY.llm, GATEWAY.embedding, GATEWAY.reranker):
            if worker: worker.stop()


if __name__ == "__main__":
    main()
