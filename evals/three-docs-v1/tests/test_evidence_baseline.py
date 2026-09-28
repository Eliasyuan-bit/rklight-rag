import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "evidence_baseline.py"


def load_module():
    spec = importlib.util.spec_from_file_location("evidence_baseline_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class EvidenceBaselineTest(unittest.TestCase):
    def test_normalizes_generated_markdown_name_and_detects_expected_source(self):
        module = load_module()
        item = {
            "expected_source": "burn_stress使用说明_1.0.4.md",
            "references": [{"file_path": "burn_stress使用说明_1.0.4.kg.md", "content": ["prefill×150ms"]}],
            "evidence": [{"quote": "prefill×150ms"}],
            "http_status": 200,
            "error": None,
        }
        assessment = module.automatic_assessment(item)
        self.assertTrue(assessment["api_ok"])
        self.assertTrue(assessment["expected_source_cited"])
        self.assertEqual(assessment["final_evidence_visible"], "pass")

    def test_missing_visible_quote_is_unknown_not_automatic_failure(self):
        module = load_module()
        item = {
            "expected_source": "source.md",
            "references": [{"file_path": "source.md", "content": ["short citation"]}],
            "evidence": [{"quote": "not in shortened citation"}],
            "http_status": 200,
            "error": None,
        }
        assessment = module.automatic_assessment(item)
        self.assertEqual(assessment["final_evidence_visible"], "unknown")

    def test_hydrates_historical_result_without_overwriting_review(self):
        module = load_module()
        item = {"question": "USB错误是为什么?", "assessment": {"answer_correct": "fail"}}
        module.hydrate_item(item, {"source": "ft", "question": item["question"]}, {"ft": "ft.md"})
        self.assertEqual(item["expected_source"], "ft.md")
        self.assertEqual(item["assessment"]["answer_correct"], "fail")
        self.assertEqual(item["retrieval_trace_id"], module.trace_id(item["question"]))

    def test_api_error_is_classified_without_manual_guessing(self):
        module = load_module()
        assessment = module.assessment_for_item({"http_status": None, "error": "timed out"})
        self.assertEqual(assessment["review"]["primary_failure"], "api_error")
        self.assertEqual(assessment["review"]["answer_correct"], "fail")

    def test_merge_script_prefers_later_duplicate_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.json"
            second = root / "second.json"
            output = root / "merged.json"
            cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]
            first.write_text(json.dumps({"run_id": "first", "results": [
                {"case_id": case["id"], "question": case["question"], "answer": "first"}
                for case in cases
            ]}, ensure_ascii=False), encoding="utf-8")
            second.write_text(json.dumps({"run_id": "second", "results": [
                {"case_id": "FT02", "question": "FT 测试中 USB 错误是为什么？", "answer": "later"}
            ]}, ensure_ascii=False), encoding="utf-8")
            subprocess.run(
                ["python3", str(ROOT / "merge_runs.py"), str(first), str(second), "--output", str(output)],
                check=True, capture_output=True, text=True,
            )
            merged = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(merged["results"]), 60)
            self.assertEqual(next(item for item in merged["results"] if item["case_id"] == "FT02")["answer"], "later")


if __name__ == "__main__":
    unittest.main()
