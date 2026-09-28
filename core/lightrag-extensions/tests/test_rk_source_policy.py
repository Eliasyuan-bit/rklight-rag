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

    def test_metric_query_prefers_table_with_header_before_matching_row(self):
        module = load_module()
        chunks = [
            {
                "chunk_id": "orphan-row",
                "content": (
                    "Qwen2.5-7B RK1828 128 128 162.25 14.19 70.47\n"
                    "VLM Model Performance ModelName Accelerator TTFT Decode TPS"
                ),
                "rerank_score": 0.999,
            },
            {
                "chunk_id": "complete-table",
                "content": (
                    "ModelName Accelerator InputTokens NewTokens TTFT(ms) TPOT(ms) DecodeTPS\n"
                    "Qwen2.5-0.5B RK182X 128 128 22.74 4.48 223.40\n"
                    "Qwen2.5-7B RK1828 128 128 162.25 14.19 70.47"
                ),
                "rerank_score": 0.989,
            },
        ]

        result = module.apply_source_authority_policy(
            chunks, "Qwen2.5-7B的性能如何？"
        )

        self.assertEqual(result[0]["chunk_id"], "complete-table")
        self.assertEqual(result[0]["table_evidence_boost"], 1.5)
        self.assertTrue(result[0]["content"].startswith("ModelName Accelerator"))
        self.assertNotIn("orphan", result[0]["content"])
        self.assertEqual(len(result), 1)

    def test_table_boost_is_not_applied_to_non_metric_question(self):
        module = load_module()
        chunk = {
            "chunk_id": "table",
            "content": "ModelName Accelerator InputTokens TTFT Qwen2.5-7B RK1828",
            "rerank_score": 0.9,
        }
        result = module.apply_source_authority_policy(
            [chunk], "Qwen2.5-7B从哪里下载？"
        )
        self.assertEqual(result[0]["table_evidence_boost"], 1.0)

    def test_base_model_query_does_not_boost_omni_table(self):
        module = load_module()
        chunk = {
            "chunk_id": "omni-table",
            "content": (
                "Full-ModalModelPerformance\n"
                "ModelName Accelerator Vision Audio TTFT DecodeTPS\n"
                "Qwen2.5-Omni RK1828 392*392 22001 9360 8696 10401"
            ),
            "rerank_score": 0.99,
        }
        result = module.apply_source_authority_policy(
            [chunk], "Qwen2.5各个大小模型的性能如何？"
        )
        self.assertEqual(result[0]["table_evidence_boost"], 1.0)

    def test_diagnostic_query_prefers_direct_text_over_same_upload_kg_summary(self):
        module = load_module()
        chunks = [
            {
                "chunk_id": "usb-flow",
                "source_group_id": "upload-1:manual.md",
                "file_path": "manual.text.md",
                "content": "USB CherryUSB ADB speed=5000; date output must contain local " * 4,
                "rerank_score": 1.437,
            },
            {
                "chunk_id": "broad-summary",
                "source_group_id": "upload-1:manual.md",
                "file_path": "manual.kg.md",
                "content": "USB error; POWER current table; FAN wiring example " * 4,
                "rerank_score": 0.395,
            },
            {
                "chunk_id": "usb-row",
                "source_group_id": "upload-1:manual.md",
                "file_path": "manual.text.md",
                "content": "USB connection and ADB communication failed " * 5,
                "rerank_score": 0.137,
            },
            {
                "chunk_id": "weak-tail",
                "source_group_id": "upload-1:manual.md",
                "file_path": "manual.text.md",
                "content": "unrelated setup details " * 10,
                "rerank_score": 0.011,
            },
        ]

        result = module.apply_source_authority_policy(chunks, "USB错误是为什么？")

        self.assertEqual([item["chunk_id"] for item in result], ["usb-flow"])

    def test_non_diagnostic_query_retains_kg_and_low_score_candidates(self):
        module = load_module()
        chunks = [
            {
                "chunk_id": "raw",
                "source_group_id": "upload-1:manual.md",
                "file_path": "manual.text.md",
                "content": "raw evidence",
                "rerank_score": 0.9,
            },
            {
                "chunk_id": "kg",
                "source_group_id": "upload-1:manual.md",
                "file_path": "manual.kg.md",
                "content": "relationship summary",
                "rerank_score": 0.2,
            },
        ]

        result = module.apply_source_authority_policy(chunks, "介绍整体测试结构")

        self.assertEqual([item["chunk_id"] for item in result], ["raw", "kg"])

    def test_diagnostic_query_does_not_fill_fixed_top_k_with_context(self):
        module = load_module()
        chunks = [
            {
                "chunk_id": f"evidence-{index}",
                "file_path": "manual.text.md",
                "content": "direct diagnostic evidence " * 10,
                "rerank_score": score,
            }
            for index, score in enumerate((1.4, 1.2, 0.8), 1)
        ]

        result = module.apply_source_authority_policy(chunks, "测试失败的原因是什么？")

        self.assertEqual(
            [item["chunk_id"] for item in result], ["evidence-1", "evidence-2"]
        )

    def test_diagnostic_table_keeps_only_rows_matching_query_identifier(self):
        module = load_module()
        content = "\n".join(
            [
                "| SN_MATCH_SOC | SN号与SOC型号匹配失败 | 检查SN |",
                "| USB | USB连接及ADB通信测试失败 | 查找CherryUSB ADB设备 |",
                "| SARADC0_BOOT | SARADC IN7连通性测试失败 | 读取ADC |",
            ]
        )
        chunks = [
            {
                "chunk_id": "error-table",
                "file_path": "manual.text.md",
                "content": content,
                "rerank_score": 1.2,
            }
        ]

        result = module.apply_source_authority_policy(
            chunks, "FT中的USB连接错误有哪些直接触发条件？"
        )

        self.assertEqual(len(result), 1)
        self.assertIn("| USB |", result[0]["content"])
        self.assertNotIn("SN_MATCH_SOC", result[0]["content"])
        self.assertNotIn("SARADC0_BOOT", result[0]["content"])
        self.assertTrue(result[0]["diagnostic_table_compacted"])

    def test_diagnostic_table_without_explicit_identifier_is_not_compacted(self):
        module = load_module()
        content = "| USB | USB失败 |\n| FAN | 风扇失败 |"

        result = module.apply_source_authority_policy(
            [
                {
                    "chunk_id": "error-table",
                    "file_path": "manual.text.md",
                    "content": content,
                    "rerank_score": 1.2,
                }
            ],
            "功能测试失败的原因是什么？",
        )

        self.assertEqual(result[0]["content"], content)

    def test_diagnostic_json_table_keeps_only_matching_rows(self):
        module = load_module()
        content = (
            '<table id="errors" format="json">'
            '[["USB", "USB连接失败", "查找CherryUSB ADB"], '
            '["SET_PN", "写入产品号失败", "进入Loader模式"], '
            '["PN_GET", "读取产品号失败", "读取PN字段"]]'
            '</table>\n<table format="json">[["PMIC", "电流范围"]]</table>'
        )

        result = module.apply_source_authority_policy(
            [{
                "chunk_id": "json-error-table",
                "file_path": "manual.text.md",
                "content": content,
                "rerank_score": 1.2,
            }],
            "FT测试中USB错误是为什么？",
        )

        self.assertIn('"USB"', result[0]["content"])
        self.assertNotIn("SET_PN", result[0]["content"])
        self.assertNotIn("PN_GET", result[0]["content"])
        self.assertNotIn("PMIC", result[0]["content"])
        self.assertTrue(result[0]["diagnostic_table_compacted"])

    def test_diagnostic_query_selects_matching_markdown_section(self):
        module = load_module()
        content = "\n\n".join(
            [
                "### POWER_12V\n12V current failure details",
                "### USB - USB自动测试项\n查找CherryUSB ADB。\n验证date输出包含local。",
                "### SARADC0_BOOT\nADC failure details",
            ]
        )

        result = module.apply_source_authority_policy(
            [
                {
                    "chunk_id": "multi-section",
                    "file_path": "manual.text.md",
                    "content": content,
                    "rerank_score": 1.0,
                }
            ],
            "FT测试中USB错误是为什么？",
        )

        self.assertIn("### USB", result[0]["content"])
        self.assertNotIn("POWER_12V", result[0]["content"])
        self.assertNotIn("SARADC0_BOOT", result[0]["content"])
        self.assertTrue(result[0]["named_section_compacted"])

    def test_explanatory_query_selects_named_section_and_drops_other_chunks(self):
        module = load_module()
        chunks = [
            {
                "chunk_id": "flows",
                "file_path": "manual.text.md",
                "content": (
                    "### USB - USB自动测试项\n查找CherryUSB ADB并验证date输出。\n\n"
                    "### SET_PN - 写入产品号\n进入Loader写入产品号。\n\n"
                    "### GET_PN - 读取产品号\n读取PN字段。"
                ),
                "rerank_score": 1.2,
            },
            {
                "chunk_id": "errors",
                "file_path": "manual.text.md",
                "content": "USB、SARADC、SET_PN错误处理汇总 " * 10,
                "rerank_score": 1.1,
            },
        ]

        result = module.apply_source_authority_policy(chunks, "介绍一下USB测试")

        self.assertEqual([item["chunk_id"] for item in result], ["flows"])
        self.assertIn("### USB", result[0]["content"])
        self.assertNotIn("SET_PN", result[0]["content"])
        self.assertNotIn("GET_PN", result[0]["content"])
        self.assertTrue(result[0]["named_section_compacted"])

    def test_document_title_does_not_hide_chinese_intent_section(self):
        module = load_module()
        content = (
            "# burn_stress 使用说明\n\n"
            "## 版本检查\n```\nburn_stress -V\n```\n"
            "version=V1.0.4_20260806\n\n"
            "## 用法\nburn_stress [-n N] [-v]\n"
        )
        result = module.apply_source_authority_policy(
            [{
                "chunk_id": "version-command",
                "file_path": "burn_stress.text.md",
                "content": content,
                "rerank_score": 1.0,
            }],
            "burn_stress检查版本怎么做",
        )

        self.assertIn("## 版本检查", result[0]["content"])
        self.assertIn("burn_stress -V", result[0]["content"])
        self.assertNotIn("## 用法", result[0]["content"])

    def test_heading_only_wrapper_is_never_a_compaction_result(self):
        module = load_module()
        content = (
            "# burn_stress 使用说明\n"
            "## 修订记录\nV1.0.4 修复NPU测试\n"
        )
        compacted, score = module._compact_named_sections(
            "burn_stress版本如何输出", content
        )
        self.assertIsNone(compacted)
        self.assertEqual(score, 0)

    def test_protected_exact_section_wins_equal_heading_match(self):
        module = load_module()
        result = module.apply_source_authority_policy(
            [
                {
                    "chunk_id": "version",
                    "content": "## 版本检查\nburn_stress -V\nversion=V1.0.4",
                    "rerank_score": 0.7,
                },
                {
                    "chunk_id": "runtime-output",
                    "content": "## 输出说明\nrunning DRAM loops=2",
                    "rerank_score": 0.9,
                    "exact_retrieval_protected": True,
                },
            ],
            "burn_stress版本如何输出",
        )
        self.assertEqual([item["chunk_id"] for item in result], ["version"])

    def test_mermaid_edges_are_not_treated_as_markdown_table_rows(self):
        module = load_module()
        content = "\n".join(
            [
                "### USB",
                "A --> B{USB3.0?}",
                "B -->|no| C[USB error]",
                "B -->|yes| D[success]",
            ]
        )

        result = module.apply_source_authority_policy(
            [
                {
                    "chunk_id": "mermaid",
                    "file_path": "manual.text.md",
                    "content": content,
                    "rerank_score": 1.0,
                }
            ],
            "USB错误是为什么？",
        )

        self.assertEqual(result[0]["content"], content)
        self.assertNotIn("diagnostic_table_compacted", result[0])

    def test_named_numbered_item_excludes_neighbouring_workflow_steps(self):
        module = load_module()
        chunks = [
            {
                "chunk_id": "ft1",
                "file_path": "manual.kg.md",
                "content": (
                    "1. **上电并获取电流**：供电\n"
                    "2. **获取 RK182x SN**：读取SN\n"
                    "3. **RK182x M2-2280 FT1自动测试**：下载update.img\n"
                    "   - USB\n   - MEMORY\n"
                    "4. **停止测试并下电**：断电"
                ),
                "rerank_score": 0.99,
            },
            {
                "chunk_id": "fit1",
                "file_path": "manual.kg.md",
                "content": (
                    "1. **上电并获取电流**：供电\n"
                    "2. **RK182x M2-2280 FIT1自动测试**：写入产品号\n"
                    "3. **停止测试并下电**：断电"
                ),
                "rerank_score": 1.0,
            },
        ]

        result = module.apply_source_authority_policy(
            chunks, "RK182x M2-2280 FT1自动测试具体是什么内容"
        )

        self.assertEqual([item["chunk_id"] for item in result], ["ft1"])
        self.assertIn("下载update.img", result[0]["content"])
        self.assertNotIn("获取 RK182x SN", result[0]["content"])
        self.assertNotIn("停止测试并下电", result[0]["content"])
        self.assertTrue(result[0]["named_item_compacted"])


if __name__ == "__main__":
    unittest.main()
