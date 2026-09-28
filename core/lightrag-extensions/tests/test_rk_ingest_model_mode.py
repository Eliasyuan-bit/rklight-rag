import asyncio
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "rk_ingest_model_mode.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rk_ingest_model_mode_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class IngestModelModeTest(unittest.TestCase):
    def test_transition_stays_active_until_query_workers_are_restored(self):
        module = load_module()
        calls = []

        def switch(path):
            calls.append(path)
            return {"ok": True}

        with patch.dict(os.environ, {"RK_INGEST_MODEL_MODE_ENABLED": "1"}), \
             patch.object(module, "_switch", side_effect=switch):
            asyncio.run(module.enter_ingest_model_mode())
            self.assertTrue(module.model_transition_active())
            asyncio.run(module.leave_ingest_model_mode())
            self.assertFalse(module.model_transition_active())

        self.assertEqual(calls, ["/admin/ingest/begin", "/admin/ingest/end"])

    def test_failed_restore_does_not_publish_ready_state(self):
        module = load_module()

        def switch(path):
            if path.endswith("/end"):
                raise RuntimeError("restore failed")
            return {"ok": True}

        with patch.dict(os.environ, {"RK_INGEST_MODEL_MODE_ENABLED": "1"}), \
             patch.object(module, "_switch", side_effect=switch):
            asyncio.run(module.enter_ingest_model_mode())
            with self.assertRaisesRegex(RuntimeError, "restore failed"):
                asyncio.run(module.leave_ingest_model_mode())
            self.assertTrue(module.model_transition_active())


if __name__ == "__main__":
    unittest.main()
