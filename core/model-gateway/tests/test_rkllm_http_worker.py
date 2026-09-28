import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "rk1828_model_gateway.py"
SPEC = importlib.util.spec_from_file_location("rk1828_model_gateway_http", MODULE_PATH)
gateway_module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gateway_module)


class FakeResponse:
    def __init__(self, body=b"", *, status=200, lines=None):
        self.body = body
        self.status = status
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body

    def __iter__(self):
        return iter(self.lines or [])


class AlreadyRunningProcess:
    def poll(self):
        return None


class RkllmHttpWorkerTest(unittest.TestCase):
    def make_worker(self):
        worker = gateway_module.RkllmHttpWorker(
            "llm", "rkllm3-server", "http://127.0.0.1:8080", "qwen3.5-4b"
        )
        worker.process = AlreadyRunningProcess()
        return worker

    def test_non_stream_request_uses_request_level_n_predict(self):
        worker = self.make_worker()
        response_body = json.dumps(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "完成"},
                        "finish_reason": "length",
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 64,
                    "total_tokens": 164,
                },
            }
        ).encode()
        calls = []

        def fake_open(path, payload=None, *, timeout):
            calls.append((path, payload, timeout))
            return FakeResponse(response_body)

        worker._open = fake_open
        result = worker.request(
            {
                "model": "qwen3.5-4b-query",
                "messages": [{"role": "user", "content": "测试"}],
                "max_new_tokens": 64,
                "enable_thinking": False,
            }
        )

        sent = calls[0][1]
        self.assertEqual(sent["model"], "qwen3.5-4b")
        self.assertEqual(sent["max_tokens"], 64)
        self.assertEqual(sent["n_predict"], 64)
        self.assertFalse(sent["cache_prompt"])
        self.assertEqual(
            sent["chat_template_kwargs"], {"enable_thinking": False}
        )
        self.assertEqual(result["text"], "完成")
        self.assertEqual(result["finish_reason"], "length")
        self.assertEqual(result["metrics"]["input_tokens"], 100)

    def test_stream_forwards_content_and_finish_reason(self):
        worker = self.make_worker()
        events = [
            {"choices": [{"delta": {"content": "你"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "好"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 16, "completion_tokens": 2, "total_tokens": 18},
             "timings": {"prompt_ms": 90.4, "predicted_ms": 11.7,
                         "predicted_per_second": 85.5}},
        ]
        lines = [
            ("data: " + json.dumps(event, ensure_ascii=False) + "\n").encode()
            for event in events
        ] + [b"data: [DONE]\n"]
        requests = []

        def fake_open(path, payload, *, timeout):
            requests.append(payload)
            return FakeResponse(lines=lines)

        worker._open = fake_open
        deltas = []

        result = worker.request_stream(
            {
                "messages": [{"role": "user", "content": "测试"}],
                "max_new_tokens": 32,
            },
            deltas.append,
        )

        self.assertEqual(deltas, ["你", "好"])
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(requests[0]["stream_options"], {"include_usage": True})
        self.assertEqual(result["metrics"]["input_tokens"], 16)
        self.assertEqual(result["metrics"]["output_tokens"], 2)
        self.assertEqual(result["metrics"]["predicted_per_second"], 85.5)

    def test_multiple_system_messages_are_folded_for_qwen_template(self):
        worker = self.make_worker()

        body = worker._chat_payload(
            {
                "messages": [
                    {"role": "system", "content": "grounding"},
                    {"role": "system", "content": "RAG role"},
                    {"role": "user", "content": "question"},
                ],
                "max_new_tokens": 128,
            },
            stream=True,
        )

        self.assertEqual(
            body["messages"],
            [
                {"role": "system", "content": "grounding\n\nRAG role"},
                {"role": "user", "content": "question"},
            ],
        )

    def test_gateway_prefers_rkllm_server_backend_when_configured(self):
        with patch.dict(
            gateway_module.os.environ,
            {
                "RK_LLM_SERVER_COMMAND": "rkllm3-server --port 8080",
                "RK_LLM_SERVER_URL": "http://127.0.0.1:8080",
                "RK_LLM_COMMAND": "legacy-daemon --daemon",
            },
            clear=False,
        ):
            worker = gateway_module.llm_worker_from_env()

        self.assertIsInstance(worker, gateway_module.RkllmHttpWorker)
        self.assertEqual(worker.command, ["rkllm3-server", "--port", "8080"])


if __name__ == "__main__":
    unittest.main()
