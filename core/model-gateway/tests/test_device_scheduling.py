import importlib.util
import os
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "rk1828_model_gateway.py"
SPEC = importlib.util.spec_from_file_location("rk1828_model_gateway_scheduling", MODULE_PATH)
gateway_module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gateway_module)


class BlockingWorker:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def request(self, payload):
        self.entered.set()
        self.release.wait(timeout=2)
        return payload


class RecordingWorker:
    def __init__(self) -> None:
        self.entered = threading.Event()

    def request(self, payload):
        self.entered.set()
        return payload


class StartupWorker:
    def __init__(self, name, starts):
        self.name = name
        self.starts = starts

    def start(self):
        self.starts.append(self.name)


class LifecycleWorker(RecordingWorker):
    def __init__(self, name, events):
        super().__init__()
        self.name = name
        self.events = events
        self.process = None

    def start(self):
        self.events.append(("start", self.name))

    def stop(self):
        self.events.append(("stop", self.name))


class LifecycleLlm(LifecycleWorker):
    def request(self, payload):
        self.events.append(("request", self.name))
        return payload

    def request_stream(self, payload, on_delta):
        self.events.append(("request_stream", self.name))
        on_delta("token")
        return payload


class DeviceSchedulingTest(unittest.TestCase):
    def make_gateway(self, single_device: bool):
        value = "1" if single_device else "0"
        with patch.dict(os.environ, {"RK_GATEWAY_SINGLE_DEVICE": value}, clear=False):
            return gateway_module.Gateway()

    def test_single_device_serializes_llm_and_embedding(self):
        gateway = self.make_gateway(single_device=True)
        llm = BlockingWorker()
        embedding = RecordingWorker()
        gateway.llm = llm
        gateway.embedding = embedding

        llm_thread = threading.Thread(target=gateway.request_llm, args=({"kind": "llm"},))
        vector_thread = threading.Thread(
            target=gateway.request_vector,
            args=(embedding, {"kind": "embedding"}),
        )
        llm_thread.start()
        self.assertTrue(llm.entered.wait(timeout=1))
        vector_thread.start()
        time.sleep(0.05)
        self.assertFalse(embedding.entered.is_set())

        llm.release.set()
        llm_thread.join(timeout=1)
        vector_thread.join(timeout=1)
        self.assertTrue(embedding.entered.is_set())

    def test_two_device_mode_allows_llm_and_embedding_overlap(self):
        gateway = self.make_gateway(single_device=False)
        llm = BlockingWorker()
        embedding = RecordingWorker()
        gateway.llm = llm
        gateway.embedding = embedding

        llm_thread = threading.Thread(target=gateway.request_llm, args=({"kind": "llm"},))
        llm_thread.start()
        self.assertTrue(llm.entered.wait(timeout=1))
        gateway.request_vector(embedding, {"kind": "embedding"})
        self.assertTrue(embedding.entered.is_set())
        llm.release.set()
        llm_thread.join(timeout=1)

    def test_single_device_warms_larger_reranker_before_embedding(self):
        starts = []
        gateway = self.make_gateway(single_device=True)
        gateway.llm = StartupWorker("llm", starts)
        gateway.embedding = StartupWorker("embedding", starts)
        gateway.reranker = StartupWorker("reranker", starts)

        with patch.dict(
            os.environ,
            {"RK_GATEWAY_EAGER_WORKERS": "llm,embedding,reranker"},
            clear=False,
        ):
            gateway.warmup()

        self.assertEqual(starts, ["llm", "reranker", "embedding"])

    def test_ingest_mode_stops_reranker_and_restores_vector_workers_in_order(self):
        with patch.dict(
            os.environ,
            {
                "RK_GATEWAY_SINGLE_DEVICE": "1",
                "RK_GATEWAY_INGEST_MODE_ENABLED": "1",
                "RK_GATEWAY_MODEL_STOP_SETTLE_SECONDS": "0",
            },
            clear=False,
        ):
            gateway = gateway_module.Gateway()
        events = []
        gateway.embedding = LifecycleWorker("embedding", events)
        gateway.reranker = LifecycleWorker("reranker", events)

        gateway.enter_ingest_mode()
        self.assertTrue(gateway.ingest_mode)
        self.assertEqual(events, [("stop", "reranker")])

        gateway.leave_ingest_mode()
        self.assertFalse(gateway.ingest_mode)
        self.assertEqual(
            events,
            [
                ("stop", "reranker"),
                ("stop", "embedding"),
                ("start", "reranker"),
                ("start", "embedding"),
            ],
        )

    def test_reranker_waits_until_query_mode_is_restored(self):
        with patch.dict(
            os.environ,
            {
                "RK_GATEWAY_INGEST_MODE_ENABLED": "1",
                "RK_GATEWAY_MODEL_STOP_SETTLE_SECONDS": "0",
            },
            clear=False,
        ):
            gateway = gateway_module.Gateway()
        events = []
        reranker = LifecycleWorker("reranker", events)
        gateway.reranker = reranker
        gateway.embedding = LifecycleWorker("embedding", events)
        gateway.enter_ingest_mode()

        request_thread = threading.Thread(
            target=gateway.request_reranker, args=({"kind": "rerank"},)
        )
        request_thread.start()
        time.sleep(0.05)
        self.assertFalse(reranker.entered.is_set())

        gateway.leave_ingest_mode()
        request_thread.join(timeout=1)
        self.assertTrue(reranker.entered.is_set())

    def test_final_query_waits_until_ingest_model_is_released(self):
        gateway = self.make_gateway(single_device=True)
        query_llm = RecordingWorker()
        gateway.llm = query_llm
        with gateway.mode_condition:
            gateway.ingest_mode = True

        request_thread = threading.Thread(
            target=gateway.request_final_query_llm,
            args=({"kind": "query"},),
        )
        request_thread.start()
        time.sleep(0.05)
        self.assertFalse(query_llm.entered.is_set())

        with gateway.mode_condition:
            gateway.ingest_mode = False
            gateway.mode_condition.notify_all()
        request_thread.join(timeout=1)
        self.assertTrue(query_llm.entered.is_set())

    def test_ingest_aux_llm_runs_inside_ingest_mode_without_model_churn(self):
        with patch.dict(
            os.environ,
            {
                "RK_GATEWAY_SINGLE_DEVICE": "1",
                "RK_GATEWAY_INGEST_MODE_ENABLED": "1",
                "RK_GATEWAY_LLM_EXCLUSIVE": "1",
                "RK_GATEWAY_LLM_STOP_WORKERS": "embedding,reranker",
                "RK_GATEWAY_MODEL_STOP_SETTLE_SECONDS": "0",
            },
            clear=False,
        ):
            gateway = gateway_module.Gateway()
        events = []
        gateway.llm = LifecycleLlm("llm", events)
        gateway.embedding = LifecycleWorker("embedding", events)
        gateway.reranker = LifecycleWorker("reranker", events)
        gateway.enter_ingest_mode()

        result = gateway.request_aux_llm({"id": "extract"})

        self.assertEqual(result, {"id": "extract"})
        self.assertEqual(events, [("stop", "reranker"), ("request", "llm")])

    def test_ingest_mode_switches_2b_to_4b_once_and_restores_query_layout(self):
        with patch.dict(
            os.environ,
            {
                "RK_GATEWAY_SINGLE_DEVICE": "1",
                "RK_GATEWAY_INGEST_MODE_ENABLED": "1",
                "RK_GATEWAY_MODEL_STOP_SETTLE_SECONDS": "0",
            },
            clear=False,
        ):
            gateway = gateway_module.Gateway()
        events = []
        query_llm = LifecycleLlm("query_llm", events)
        ingest_llm = LifecycleLlm("ingest_llm", events)
        gateway.query_llm = query_llm
        gateway.ingest_llm = ingest_llm
        gateway.llm = query_llm
        gateway.embedding = LifecycleWorker("embedding", events)
        gateway.reranker = LifecycleWorker("reranker", events)

        gateway.enter_ingest_mode()
        self.assertIs(gateway.llm, ingest_llm)
        self.assertEqual(
            events,
            [
                ("stop", "reranker"),
                ("stop", "embedding"),
                ("stop", "query_llm"),
                ("start", "ingest_llm"),
            ],
        )

        gateway.request_aux_llm({"id": "extract"})
        gateway.leave_ingest_mode()

        self.assertIs(gateway.llm, query_llm)
        self.assertEqual(
            events,
            [
                ("stop", "reranker"),
                ("stop", "embedding"),
                ("stop", "query_llm"),
                ("start", "ingest_llm"),
                ("request", "ingest_llm"),
                ("stop", "embedding"),
                ("stop", "ingest_llm"),
                ("start", "query_llm"),
                ("start", "reranker"),
                ("start", "embedding"),
            ],
        )

    def test_final_query_temporarily_releases_vector_models(self):
        with patch.dict(
            os.environ,
            {
                "RK_GATEWAY_SINGLE_DEVICE": "1",
                "RK_GATEWAY_LLM_EXCLUSIVE": "1",
                "RK_GATEWAY_LLM_STOP_WORKERS": "embedding,reranker",
                "RK_GATEWAY_MODEL_STOP_SETTLE_SECONDS": "0",
            },
            clear=False,
        ):
            gateway = gateway_module.Gateway()
        events = []
        gateway.llm = LifecycleLlm("llm", events)
        gateway.embedding = LifecycleWorker("embedding", events)
        gateway.reranker = LifecycleWorker("reranker", events)

        result = gateway.request_llm({"id": "keyword-or-query"})

        self.assertEqual(result, {"id": "keyword-or-query"})
        self.assertEqual(
            events,
            [
                ("stop", "embedding"),
                ("stop", "reranker"),
                ("request", "llm"),
                ("start", "reranker"),
                ("start", "embedding"),
            ],
        )

    def test_final_stream_restores_models_after_generation(self):
        with patch.dict(
            os.environ,
            {
                "RK_GATEWAY_SINGLE_DEVICE": "1",
                "RK_GATEWAY_LLM_EXCLUSIVE": "1",
                "RK_GATEWAY_LLM_STOP_WORKERS": "embedding,reranker",
                "RK_GATEWAY_MODEL_STOP_SETTLE_SECONDS": "0",
            },
            clear=False,
        ):
            gateway = gateway_module.Gateway()
        events = []
        deltas = []
        gateway.llm = LifecycleLlm("llm", events)
        gateway.embedding = LifecycleWorker("embedding", events)
        gateway.reranker = LifecycleWorker("reranker", events)

        gateway.request_llm_stream({"id": "query"}, deltas.append)

        self.assertEqual(deltas, ["token"])
        self.assertEqual(events[-2:], [("start", "reranker"), ("start", "embedding")])

    def test_exclusive_llm_can_release_embedding_only(self):
        with patch.dict(
            os.environ,
            {
                "RK_GATEWAY_SINGLE_DEVICE": "1",
                "RK_GATEWAY_LLM_EXCLUSIVE": "1",
                "RK_GATEWAY_LLM_STOP_WORKERS": "embedding",
                "RK_GATEWAY_MODEL_STOP_SETTLE_SECONDS": "0",
            },
            clear=False,
        ):
            gateway = gateway_module.Gateway()
        events = []
        gateway.llm = LifecycleLlm("llm", events)
        gateway.embedding = LifecycleWorker("embedding", events)
        gateway.reranker = LifecycleWorker("reranker", events)

        gateway.request_llm({"id": "query"})

        self.assertEqual(
            events,
            [
                ("stop", "embedding"),
                ("request", "llm"),
                ("start", "embedding"),
            ],
        )

if __name__ == "__main__":
    unittest.main()
