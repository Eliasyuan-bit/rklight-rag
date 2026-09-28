import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "rk_source_policy.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rk_source_policy_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class SourcePolicyTest(unittest.TestCase):
    def test_primary_evidence_outranks_derived_answer(self):
        module = load_module()
        chunks = [
            {"chunk_id": "derived", "file_path": "系统技术方案.md", "content": "x" * 500, "rerank_score": 0.99},
            {"chunk_id": "primary", "file_path": "1820_test.md", "content": "x" * 500, "rerank_score": 0.50},
        ]
        with patch.dict(os.environ, {"RK_DERIVED_SOURCE_PATTERNS": "技术方案"}):
            result = module.apply_source_authority_policy(chunks)
        self.assertEqual(result[0]["chunk_id"], "primary")
        self.assertEqual(result[1]["source_authority"], "derived")
        self.assertEqual(chunks[0]["rerank_score"], 0.99)

    def test_short_question_is_penalized_but_short_command_is_not(self):
        module = load_module()
        result = module.apply_source_authority_policy([
            {"chunk_id": "question", "content": "USB为什么有问题？", "rerank_score": 1.0},
            {"chunk_id": "command", "content": "curl --unix-socket /tmp/rag.sock", "rerank_score": 0.5},
        ])
        self.assertEqual(result[0]["chunk_id"], "command")
        self.assertEqual(result[1]["evidence_quality"], "thin")

    def test_multiple_domain_identifiers_boost_exact_evidence(self):
        module = load_module()
        expansion = '{"usb":["USB_TEST","CherryUSB ADB","speed=5000","timestamps:"]}'
        chunks = [
            {"chunk_id": "summary", "content": "USB_TEST failed", "rerank_score": 0.95},
            {
                "chunk_id": "flow",
                "content": "USB_TEST product=CherryUSB ADB speed=5000 timestamps:",
                "rerank_score": 0.50,
            },
        ]
        with patch.dict(os.environ, {"RK_LEXICAL_QUERY_EXPANSIONS": expansion}):
            result = module.apply_source_authority_policy(chunks, "USB错误")
        self.assertEqual(result[0]["chunk_id"], "flow")
        self.assertEqual(result[0]["exact_evidence_hits"], 4)


if __name__ == "__main__":
    unittest.main()
