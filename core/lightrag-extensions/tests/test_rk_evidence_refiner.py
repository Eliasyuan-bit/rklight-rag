import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
import sys
import tempfile


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
    async def test_preserves_bounded_protected_document_fact_passage(self):
        module = load_module()
        content = (
            "## Add Call Queue\n"
            "Open Web GUI > Basic Call Features > Call Queue and click Add.\n"
            "<table><tr><td>Extension</td><td>Configure the extension.</td></tr>"
            "<tr><td>Name</td><td>Configure the name.</td></tr></table>"
        )
        chunks = [{
            "chunk_id": "call-queue",
            "content": content,
            "exact_retrieval_protected": True,
            "retrieval_profile": "document_fact",
        }]
        with patch.dict(
            os.environ,
            {
                "RK_EVIDENCE_REFINER_ENABLED": "1",
                "RK_EVIDENCE_MIN_TOTAL_CHARS": "0",
            },
        ), patch.object(module, "_request_rerank") as rerank:
            result = await module.refine_evidence_units(
                chunks, "呼叫队列配置流程是什么？"
            )
        self.assertEqual(result[0]["content"], content)
        rerank.assert_not_called()

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

    async def test_reconstructs_table_caption_heading_header_and_row_as_one_package(self):
        module = load_module()
        chunks = [
            {
                "chunk_id": "performance",
                "content": (
                    "### 性能测试\n"
                    "LLM Model Performance\n\n"
                    "| ModelName | TTFT | TPS |\n"
                    "| --- | --- | --- |\n"
                    "| Qwen2.5-7B | 162.25ms | 70.47 |\n"
                    "| Qwen3-4B | 88.47ms | 99.00 |"
                ),
                "rerank_score": 0.9,
            }
        ]

        def scores(_query, documents):
            return [0.96 if "Qwen2.5-7B" in document else 0.02 for document in documents]

        with patch.dict(
            os.environ,
            {
                "RK_EVIDENCE_REFINER_ENABLED": "1",
                "RK_EVIDENCE_MIN_TOTAL_CHARS": "0",
                "RK_EVIDENCE_NEIGHBOR_SCORE_RATIO": "0.99",
            },
        ), patch.object(module, "_request_rerank", side_effect=scores):
            result = await module.refine_evidence_units(chunks, "Qwen2.5-7B的性能数据是多少？")

        evidence = result[0]["content"]
        self.assertIn("### 性能测试", evidence)
        self.assertIn("LLM Model Performance", evidence)
        self.assertIn("| ModelName | TTFT | TPS |", evidence)
        self.assertIn("| Qwen2.5-7B | 162.25ms | 70.47 |", evidence)
        self.assertNotIn("Qwen3-4B", evidence)

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

    async def test_late_exact_table_row_is_admitted_before_reranking(self):
        """A table row after the local cap must not disappear by source order."""
        module = load_module()
        chunks = [
            {
                "chunk_id": "performance",
                "content": (
                    "说明一。\n说明二。\n说明三。\n\n"
                    "| ModelName | TTFT | TPS |\n"
                    "| --- | --- | --- |\n"
                    "| Qwen2.5-7B | 162.25ms | 70.47 |\n"
                    "| Qwen3-4B | 88.47ms | 99.00 |"
                ),
                "rerank_score": 0.9,
            }
        ]

        def scores(_query, documents):
            return [0.98 if "Qwen2.5-7B" in document else 0.01 for document in documents]

        with patch.dict(
            os.environ,
            {
                "RK_EVIDENCE_REFINER_ENABLED": "1",
                "RK_EVIDENCE_MIN_TOTAL_CHARS": "0",
                "RK_EVIDENCE_MAX_CANDIDATES": "2",
                "RK_EVIDENCE_MAX_UNITS_PER_CHUNK": "2",
                "RK_EVIDENCE_MIN_UNITS": "2",
                "RK_EVIDENCE_NEIGHBOR_SCORE_RATIO": "0.99",
            },
        ), patch.object(module, "_request_rerank", side_effect=scores):
            result = await module.refine_evidence_units(chunks, "Qwen2.5-7B的性能数据是多少？")

        self.assertIn("Qwen2.5-7B", result[0]["content"])
        self.assertIn("| ModelName | TTFT | TPS |", result[0]["content"])
        self.assertNotIn("Qwen3-4B", result[0]["content"])

    def test_candidate_budget_is_round_robin_across_chunks(self):
        module = load_module()
        chunks = [
            {"chunk_id": "first", "content": "目标 A。目标 B。目标 C。"},
            {"chunk_id": "second", "content": "Qwen2.5-7B 性能数据。"},
        ]
        candidates = module._select_candidate_units(
            chunks, "Qwen2.5-7B性能", max_per_chunk=3, max_candidates=2
        )
        self.assertEqual({unit["chunk_index"] for unit in candidates}, {0, 1})

    def test_table_coverage_gate_drops_unvalidated_typed_parent(self):
        module = load_module()
        table_spec = importlib.util.spec_from_file_location(
            "rk_table_parent", MODULE_PATH.parent / "rk_table_parent.py"
        )
        table_module = importlib.util.module_from_spec(table_spec)
        assert table_spec.loader
        sys.modules["rk_table_parent"] = table_module
        table_spec.loader.exec_module(table_module)
        chunks = [
            {"chunk_id": "bad", "table_parent": True, "table_type": "llm_performance",
             "content": "Qwen3-4B TTFT 88.47", "table_evidence_valid": False},
            {"chunk_id": "context", "content": "性能表未提供完整列信息。"},
        ]
        result = module.apply_evidence_coverage_gate(chunks, "Qwen3-4B的性能数据是多少")
        self.assertEqual([item["chunk_id"] for item in result], ["context"])

    def test_table_coverage_gate_matches_spaced_model_identifier(self):
        module = load_module()
        table_spec = importlib.util.spec_from_file_location(
            "rk_table_parent", MODULE_PATH.parent / "rk_table_parent.py"
        )
        table_module = importlib.util.module_from_spec(table_spec)
        assert table_spec.loader
        sys.modules["rk_table_parent"] = table_module
        table_spec.loader.exec_module(table_module)
        chunks = [
            {
                "chunk_id": "server",
                "table_parent": True,
                "table_type": "server_config",
                "table_evidence_valid": True,
                "content": (
                    "- Model Name = Qwen 2.5 7B\n"
                    "- CPU = 32-core CPU\n"
                    "- Estimated Time = ~105 minutes"
                ),
            },
        ]
        result = module.apply_evidence_coverage_gate(
            chunks, "转换 Qwen2.5-7B 推荐什么服务器配置，预计多久"
        )
        self.assertEqual([item["chunk_id"] for item in result], ["server"])

    def test_contract_marks_incomplete_procedure_and_complete_command(self):
        module = load_module()
        procedure = module.apply_evidence_contract(
            [{"chunk_id": "p", "content": "只描述准备环境。"}], "如何复现部署流程"
        )
        self.assertEqual(procedure[0]["evidence_contract"]["status"], "needs_retrieval")
        command = module.apply_evidence_contract(
            [{"chunk_id": "c", "content": "执行 `rknn-smi info` 查看状态。"}], "命令怎么用"
        )
        self.assertEqual(command[0]["evidence_contract"]["status"], "pass")

    def test_contract_recovery_runs_once_and_marks_new_candidate(self):
        module = load_module()
        chunks = [{"chunk_id": "old", "content": "只描述准备环境。",
                   "evidence_contract": {"type": "procedure", "status": "needs_retrieval"}}]
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / "kv_store_text_chunks.json"
            store.write_text("{}", encoding="utf-8")
            fake_lexical = MagicMock()
            fake_lexical._bm25.return_value = [
                {"chunk_id": "new", "content": "1. 准备环境\n2. 启动服务"}
            ]
            with patch.dict(os.environ, {"RK_CONTRACT_RECOVERY_ENABLED": "true"}), patch.dict(
                sys.modules, {"rk_lexical_retrieval": fake_lexical}
            ):
                result = module.recover_contract_evidence(chunks, "如何复现部署流程", {"working_dir": directory})
        self.assertEqual([item["chunk_id"] for item in result], ["old", "new"])
        self.assertTrue(result[-1]["supplemental_retrieval"])

    def test_query_anchor_gate_removes_unrelated_sources_only_when_anchor_exists(self):
        module = load_module()
        chunks = [
            {"chunk_id": "right", "content": "ROCKRAGCLAW 部署步骤"},
            {"chunk_id": "wrong", "content": "RKNN3 测试步骤"},
        ]
        result = module.apply_query_anchor_gate(chunks, "介绍 ROCKRAGCLAW 怎么复现")
        self.assertEqual([item["chunk_id"] for item in result], ["right"])
        self.assertEqual(
            [item["chunk_id"] for item in module.apply_query_anchor_gate(chunks, "介绍 ROCKRAGCLAW 怎么复现")],
            ["right"],
        )
        self.assertEqual(module.apply_query_anchor_gate(
            [{"chunk_id": "wrong", "content": "RKNN3 测试步骤"}],
            "ROCKRAGCLAW 怎么复现",
        ), [])

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
