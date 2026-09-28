import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "rk_evidence_refiner.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rk_evidence_refiner_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class EvidenceSplitterTest(unittest.TestCase):
    def test_preserves_markdown_structure_as_units(self):
        module = load_module()
        units = module.split_evidence_units(
            """### USB 自动测试
- 查找 CherryUSB ADB
- 检查 speed=5000

### SET_PN
进入 Loader 写入产品号。
"""
        )

        self.assertEqual([unit["kind"] for unit in units], ["list_item", "list_item", "sentence"])
        self.assertEqual(units[0]["section_path"], "USB 自动测试")
        self.assertEqual(units[2]["section_path"], "SET_PN")

    def test_splits_table_rows_and_remembers_header(self):
        module = load_module()
        units = module.split_evidence_units(
            "| 项目 | 原因 |\n| --- | --- |\n| USB | 未找到设备 |\n| FAN | 未接线 |"
        )

        self.assertEqual(len(units), 2)
        self.assertEqual(units[0]["kind"], "table_row")
        self.assertIn("| 项目 | 原因 |", units[0]["table_header"])

    def test_splits_compact_json_table_into_rows(self):
        module = load_module()
        units = module.split_evidence_units(
            '<table id="errors" format="json">'
            '[["USB", "未找到设备"], ["SET_PN", "写入失败"]]'
            '</table>'
        )

        self.assertEqual(len(units), 2)
        self.assertTrue(all(unit["kind"] == "json_table_row" for unit in units))
        self.assertIn("SET_PN", units[1]["text"])


class EvidenceRefinerTest(unittest.IsolatedAsyncioTestCase):
    async def test_reranks_units_removes_noise_and_restores_source_order(self):
        module = load_module()
        chunks = [
            {
                "chunk_id": "manual-1",
                "content": (
                    "### USB 自动测试\n"
                    "查找 product=CherryUSB ADB。\n"
                    "检查 speed=5000。\n\n"
                    "### SET_PN\n"
                    "进入 Loader 并写入产品号。"
                ),
                "rerank_score": 0.9,
            }
        ]

        def scores(_query, documents):
            result = []
            for document in documents:
                if "CherryUSB" in document:
                    result.append(0.82)
                elif "speed=5000" in document:
                    result.append(0.95)
                else:
                    result.append(0.04)
            return result

        with patch.dict(
            os.environ,
            {
                "RK_EVIDENCE_REFINER_ENABLED": "1",
                "RK_EVIDENCE_MIN_TOTAL_CHARS": "0",
                "RK_EVIDENCE_NEIGHBOR_SCORE_RATIO": "0.5",
            },
        ), patch.object(module, "_request_rerank", side_effect=scores):
            result = await module.refine_evidence_units(chunks, "介绍 USB 测试")

        self.assertEqual(len(result), 1)
        self.assertIn("### USB 自动测试", result[0]["content"])
        self.assertLess(
            result[0]["content"].index("CherryUSB"),
            result[0]["content"].index("speed=5000"),
        )
        self.assertNotIn("SET_PN", result[0]["content"])
        self.assertNotIn("Loader", result[0]["content"])
        self.assertTrue(result[0]["evidence_refined"])
        self.assertEqual(result[0]["evidence_unit_count"], 2)
        self.assertEqual(len(result[0]["evidence_ranges"]), 2)

    async def test_reconstructs_table_header_for_selected_row(self):
        module = load_module()
        chunks = [
            {
                "chunk_id": "errors",
                "content": (
                    "错误表\n\n"
                    "| 项目 | 原因 |\n"
                    "| --- | --- |\n"
                    "| USB | 未找到 CherryUSB ADB |\n"
                    "| FAN | 风扇未接线 |"
                ),
                "rerank_score": 0.9,
            }
        ]

        def scores(_query, documents):
            return [0.1 if "错误表" in doc else (0.9 if "USB" in doc else 0.05) for doc in documents]

        with patch.dict(
            os.environ,
            {
                "RK_EVIDENCE_REFINER_ENABLED": "1",
                "RK_EVIDENCE_MIN_TOTAL_CHARS": "0",
                "RK_EVIDENCE_NEIGHBOR_SCORE_RATIO": "0.95",
            },
        ), patch.object(module, "_request_rerank", side_effect=scores):
            result = await module.refine_evidence_units(chunks, "USB 错误")

        self.assertIn("| 项目 | 原因 |", result[0]["content"])
        self.assertIn("| USB |", result[0]["content"])
        self.assertNotIn("| FAN |", result[0]["content"])

    async def test_reconstructs_only_selected_json_table_row(self):
        module = load_module()
        chunks = [
            {
                "chunk_id": "errors",
                "content": (
                    '<table id="errors" format="json">'
                    '[["USB", "连接失败"], ["SET_PN", "写入产品号失败"], '
                    '["SARADC", "电压异常"]]</table>'
                ),
                "rerank_score": 0.9,
            }
        ]

        def scores(_query, documents):
            return [0.95 if "SET_PN" in doc else 0.02 for doc in documents]

        with patch.dict(
            os.environ,
            {
                "RK_EVIDENCE_REFINER_ENABLED": "1",
                "RK_EVIDENCE_MIN_TOTAL_CHARS": "0",
                "RK_EVIDENCE_NEIGHBOR_SCORE_RATIO": "0.9",
            },
        ), patch.object(module, "_request_rerank", side_effect=scores):
            result = await module.refine_evidence_units(chunks, "产品号怎么写入")

        self.assertIn("SET_PN", result[0]["content"])
        self.assertNotIn("USB", result[0]["content"])
        self.assertNotIn("SARADC", result[0]["content"])
        self.assertTrue(result[0]["content"].startswith("<table"))

    async def test_reranker_failure_returns_original_chunks(self):
        module = load_module()
        chunks = [{"chunk_id": "one", "content": "第一句。第二句。第三句。" * 20}]
        with patch.dict(
            os.environ,
            {"RK_EVIDENCE_REFINER_ENABLED": "1", "RK_EVIDENCE_MIN_TOTAL_CHARS": "0"},
        ), patch.object(module, "_request_rerank", side_effect=RuntimeError("offline")):
            result = await module.refine_evidence_units(chunks, "测试")

        self.assertIs(result, chunks)

    async def test_disabled_refiner_does_not_call_reranker(self):
        module = load_module()
        chunks = [{"chunk_id": "one", "content": "第一句。第二句。第三句。" * 20}]
        with patch.dict(os.environ, {"RK_EVIDENCE_REFINER_ENABLED": "0"}), patch.object(
            module, "_request_rerank"
        ) as rerank:
            result = await module.refine_evidence_units(chunks, "测试")

        self.assertIs(result, chunks)
        rerank.assert_not_called()


if __name__ == "__main__":
    unittest.main()
