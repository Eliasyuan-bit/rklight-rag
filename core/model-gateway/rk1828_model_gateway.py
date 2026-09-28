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
        # Embedding and reranking share one RK1828 in the two-card layout.
        # JsonlWorker locks only serialize requests for the same child; this
        # lock prevents those two distinct children from issuing NPU work at
        # the same time on their shared card.
        self.vector_lock = threading.Lock()

    def request_vector(self, worker: JsonlWorker, payload: dict[str, Any]) -> dict[str, Any]:
        with self.vector_lock:
            return worker.request(payload)

    def health(self) -> dict[str, Any]:
        def state(worker: JsonlWorker | None) -> str:
            if worker is None:
                return "disabled"
            return "ready" if worker.process and worker.process.poll() is None else "not_started"

        return {"ok": True, "llm": state(self.llm), "embedding": state(self.embedding), "reranker": state(self.reranker)}

    def warmup(self) -> None:
        """Start resident workers during service boot, never on a user query.

        LLM initialization is intentionally eager by default.  Embedding and
        reranker remain lazy because they share one accelerator and are
        not required for the WebUI to become interactive. Set
        ``RK_GATEWAY_EAGER_WORKERS=llm,embedding,reranker`` only when the
        vector models are assigned to independent accelerators.
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
LLM_MODEL_ID = os.getenv("RK_LLM_MODEL", "qwen3.5-9b-110k")
QUERY_MODEL_ID = os.getenv("RK_QUERY_MODEL", LLM_MODEL_ID)
QUERY_MAX_TOKENS = int(os.getenv("RK_QUERY_MAX_TOKENS", "128"))
QUERY_SYSTEM_PROMPT = (
    "只依据检索上下文回答，不用常识补全。名称、数值、命令、路径和动作词按原文抄写。"
    "“仅X”事实只能归入X；比较对象的事实只能取自该对象标题至下一个同级标题之间。"
    "一般规则与特定例外并存时写明例外。询问当前设备而上下文无实时证据时，只说无法确认及需检查项。"
    "按问题类型只选一种格式：命令题=命令加一句说明；原因题=一句结论加最多三条直接原因；"
    "比较题=每个对象一个单行列表项，写全指定维度的动作和测试项；"
    "完整复现或部署题=恰好五个短步骤，覆盖环境、授权、部署、模型、启动验证。"
    "答案只写一遍；禁止总结、背景、无关参数、思考过程和自行生成的引用列表。"
)
QUERY_OUTPUT_SUFFIX = (
    "\n\n【输出】直接回答且只写一次。原因题最多三条后停止；比较题每对象仅一行且不得跨标题取值；"
    "完整复现或部署题恰好五个短行。不得漏掉点名对象，不得输出总结、背景或引用列表。"
)


def extract_user_query(prompt_content: str) -> str:
    """Extract LightRAG's final user query from its assembled prompt."""
    marker = "---User Query---"
    return prompt_content.rsplit(marker, 1)[-1].strip() if marker in prompt_content else prompt_content.strip()


def intent_output_suffix(query: str) -> str:
    """Return one high-priority format contract instead of competing rules."""
    folded = query.casefold()
    if any(term in folded for term in ("当前", "现在", "这台")):
        return (
            "\n【本题格式：实时状态】若上下文没有实时证据，只输出两句：第一句说无法从知识库确认；"
            "第二句说需检查当前设备或服务配置。禁止列历史方案、可能原因、排查步骤或具体命令。"
        )
    if "归类为什么错误" in folded or "归类为何错误" in folded:
        return "\n【本题格式：错误归类】只输出错误类别和一条直接判据，共一句话。"
    if any(term in folded for term in ("复现", "完整部署")):
        return (
            "\n【本题只按此模板作答】"
            "1. 环境：<关键硬件和软件>\n"
            "2. 授权：<授权输入和产物>\n"
            "3. 部署：<脚本和目标目录>\n"
            "4. 模型：<模型目录>\n"
            "5. 启动验证：<原文启动命令及验证方式>\n"
            "每个尖括号只填一个短语；不得加标题、解释或第六行。"
        )
    if any(term in folded for term in ("为什么", "原因")):
        return (
            "\n【本题格式：原因】只列上下文直接证明的原因，共一至三条；"
            "不为凑数添加第三条，列完立即结束。"
        )
    if "一样吗" in folded:
        return "\n【本题格式：通则与例外】只用一句话先写通则、再写特定方式的例外，不得分项或重复。"
    if any(term in folded for term in ("区别", "对比", "比较")):
        return (
            "\n【本题格式：比较】每个点名对象一个单行列表项；仅从其标题区间取事实；"
            "写完所有对象立即结束，不得换一种说法重复。"
        )
    if any(term in folded for term in ("命令", "怎么用", "如何通过", "怎么查看", "怎么写")):
        return "\n【本题格式：命令】只输出命令代码块和一句预期结果或说明。"
    if "哪里" in folded and any(term in folded for term in ("怎么", "如何")):
        return "\n【本题格式：位置与步骤】第一句回答位置，再输出最多两个不重复的定位步骤，不得自行列引用。"
    if any(term in folded for term in ("怎么", "如何")):
        return "\n【本题格式：步骤】只输出一至三个不重复的操作步骤，不得自行列引用。"
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
        if self.path == "/health":
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
                configured_max_tokens = int(os.environ.get("RK_LLM_DEFAULT_MAX_TOKENS", "512"))
                requested_max_tokens = int(request.get(
                    "max_completion_tokens",
                    request.get("max_tokens", request.get("max_new_tokens", configured_max_tokens)),
                ))
                # Enforce the board-wide output budget. This leaves room for
                # retrieved context within the 4K-token LLM session.
                model = request.get("model", LLM_MODEL_ID)
                is_query_model = model == QUERY_MODEL_ID
                max_allowed_tokens = (
                    min(QUERY_MAX_TOKENS, configured_max_tokens)
                    if is_query_model
                    else configured_max_tokens
                )
                max_new_tokens = min(max(requested_max_tokens, 1), max_allowed_tokens)
                print(
                    f"gateway: chat requested_max_tokens={requested_max_tokens} "
                    f"resolved_max_new_tokens={max_new_tokens} model={model}",
                    file=sys.stderr,
                    flush=True,
                )
                messages = request["messages"]
                if is_query_model:
                    # LightRAG's retrieval template is a large user message.
                    # Put the output contract at its end, nearest to the
                    # generation turn, rather than relying on a distant system
                    # instruction that a small model may underweight.
                    messages = prepare_query_messages(messages)
                worker_request = {
                    "id": request.get("id", str(uuid.uuid4())),
                    "messages": messages,
                    "max_new_tokens": max_new_tokens,
                    "enable_thinking": bool(request.get("enable_thinking", False)),
                }
                if request.get("stream", False):
                    write_delta, finish_stream = self.begin_chat_stream(model=model)
                    finish_reason = "stop"
                    try:
                        reply = GATEWAY.llm.request_stream(worker_request, write_delta)
                        finish_reason = str(reply.get("finish_reason", "stop"))
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
                reply = GATEWAY.llm.request(worker_request)
                metrics = reply.get("metrics", {})
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
                reply = GATEWAY.request_vector(
                    GATEWAY.embedding, {"id": str(uuid.uuid4()), "input": request["input"]}
                )
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
                reply = GATEWAY.request_vector(GATEWAY.reranker, worker_request)
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
