import importlib.util
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "rk_lexical_retrieval.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rk_lexical_retrieval_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class LexicalRetrievalTest(unittest.TestCase):

    def test_index_normalizes_any_spaced_technical_identifier(self):
        module = load_module()
        indexed = module._index_text(
            "Qwen 2.5 7B uses RKNN 3 SDK with DDR 4", "server_config"
        )
        self.assertIn("qwen257b", indexed)
        self.assertIn("rknn3sdk", indexed)
        self.assertIn("ddr4", indexed)
        self.assertIn("服务器 配置 推荐", indexed)

    def test_spaced_and_punctuated_identifier_share_bm25_token(self):
        module = load_module()
        query_tokens = set(module._tokens("Qwen2.5-7B"))
        source_tokens = set(module._tokens(module._index_text("Qwen 2.5 7B")))
        self.assertIn("qwen257b", query_tokens)
        self.assertIn("qwen257b", source_tokens)
    def test_trace_logs_rank_metadata_without_query_or_content(self):
        module = load_module()
        messages = []
        module.logger = types.SimpleNamespace(
            info=lambda template, *args: messages.append(template % args),
            warning=lambda *args: None,
            debug=lambda *args: None,
        )
        module.log_chunk_stage(
            "private USB question",
            "final",
            [{
                "chunk_id": "chunk-1",
                "file_path": "/docs/ft.md",
                "content": "private evidence",
                "rerank_score": 0.75,
            }],
            input_count=6,
            requested_top_k=3,
            token_budget=3000,
        )
        self.assertEqual(len(messages), 1)
        self.assertIn("stage=final", messages[0])
        self.assertIn('"chunk_id":"chunk-1"', messages[0])
        self.assertIn('"file":"ft.md"', messages[0])
        self.assertNotIn("private USB question", messages[0])
        self.assertNotIn("private evidence", messages[0])

    def test_exact_identifiers_are_in_fused_candidates(self):
        module = load_module()
        async def run_inline(function, *args):
            return function(*args)

        module.asyncio.to_thread = run_inline
        with tempfile.TemporaryDirectory() as directory:
            store = {
                "generic": {"content": "USB 测试失败时查看 Errors 日志", "file_path": "ft.md"},
                "target": {
                    "content": "USB_TEST 查找 product=CherryUSB ADB，要求 speed=5000；date 输出必须包含 timestamps:",
                    "file_path": "ft.md",
                },
                "other": {"content": "设备上电和固件下载说明", "file_path": "boot.md"},
            }
            (Path(directory) / "kv_store_text_chunks.json").write_text(
                json.dumps(store, ensure_ascii=False), encoding="utf-8"
            )
            vector = [{"chunk_id": "generic", "content": store["generic"]["content"], "file_path": "ft.md"}]
            result = asyncio.run(
                module.fuse_vector_and_lexical_chunks(
                    "USB_TEST 对应哪个 product，speed 是多少？",
                    vector,
                    {"working_dir": directory},
                    3,
                )
            )
            ids = [chunk["chunk_id"] for chunk in result]
            self.assertIn("target", ids)
            target = next(chunk for chunk in result if chunk["chunk_id"] == "target")
            self.assertGreater(target["lexical_score"], 0)

    def test_passage_window_keeps_hit_and_heading(self):
        module = load_module()
        content = "# Other\n" + ("unrelated text\n" * 300) + "# USB_TEST\nproduct=CherryUSB ADB\nspeed=5000\n" + ("tail\n" * 300)
        passage = module._best_passage(content, "USB_TEST product speed=5000")
        self.assertIn("# USB_TEST", passage)
        self.assertIn("speed=5000", passage)
        self.assertLessEqual(len(passage), 2400)

    def test_metric_table_passage_removes_prefix_and_keeps_header(self):
        module = load_module()
        content = """unrelated download links and model URLs
# ModelPerformance
This section shows benchmark results.
LLMModelPerformance
TTFT TPOT
ModelName Accelerator InputTokens NewTokens DecodeTPS
(ms) (ms)
Qwen2.5-0.5B RK182X 128 128 22.74 4.48 223.40
Qwen2.5-1.5B RK182X 128 128 49.14 6.69 149.39
Qwen2.5-3B RK182X 128 128 85.54 9.69 103.24
Qwen2.5-7B RK1828 128 128 162.25 14.19 70.47
Qwen3-0.6B RK182X 128 128 28.61 5.49 182.26
"""
        passage = module._best_passage(content, "qwen2.5各个大小模型的性能如何")
        self.assertTrue(passage.startswith("LLMModelPerformance"))
        self.assertIn("ModelName Accelerator InputTokens", passage)
        self.assertIn("Qwen2.5-0.5B", passage)
        self.assertIn("Qwen2.5-7B", passage)
        self.assertNotIn("unrelated download", passage)
        self.assertNotIn("Qwen3-0.6B", passage)

    def test_comparison_query_collects_each_named_section(self):
        module = load_module()
        content = (
            "# Intro\n" + "x" * 2500
            + "\n## FT1 测试\nSN_MATCH_SOC\n" + "a" * 1200
            + "\n## FIT1 测试\nSN_MATCH_FAN_DET and SET_PN\n" + "b" * 1200
            + "\n## IQC 测试\nGET_PN reads PN and SN\n" + "c" * 1200
        )
        passage = module._best_passage(content, "FT1、FIT1、IQC 在 SN 和 PN 上有什么区别？")
        self.assertIn("## FT1 测试", passage)
        self.assertIn("SN_MATCH_SOC", passage)
        self.assertIn("## FIT1 测试", passage)
        self.assertIn("SET_PN", passage)
        self.assertIn("## IQC 测试", passage)
        self.assertIn("GET_PN", passage)
        self.assertLessEqual(len(passage), 2400)

    def test_comparison_sections_keep_late_matching_facts(self):
        module = load_module()
        padding = "ordinary setup line\n" * 80
        content = (
            "## FT1\n获取 SN\n" + padding + "SN_MATCH_SOC only FT1\n"
            "## FIT1\n获取 SN\n" + padding + "SET_PN only FIT1\n"
            "## IQC\n获取 SN\n" + padding + "PN_GET only IQC\n"
        )
        with patch.dict("os.environ", {"RK_LEXICAL_PASSAGE_CHARS": "1200"}):
            passage = module._best_passage(
                content, "FT1 FIT1 IQC SN PN SN_MATCH_SOC SET_PN PN_GET"
            )
        self.assertIn("SN_MATCH_SOC", passage)
        self.assertIn("SET_PN only FIT1", passage)
        self.assertIn("PN_GET only IQC", passage)
        self.assertLessEqual(len(passage), 1200)

    def test_comparison_sections_exclude_unmatched_neighbouring_steps(self):
        module = load_module()
        content = (
            "## FT1\n获取 SN\n设置 SN（仅 FT1）\nFT1 自动测试并检查 Plug_DET\n"
            "## FIT1\n获取 SN\nBURN_CHECK_PN（仅 FIT1）\nSET_PN（仅 FIT1）\nFIT1 检查电流\n"
            "## IQC\n获取 SN\nPN_GET（仅 IQC）\nIQC 停止测试并检查 Plug_DET\n"
        )
        passage = module._best_passage(
            content,
            "FT1、FIT1、IQC 在 SN 和产品号处理上有什么区别？ "
            "PN BURN_CHECK_PN SET_PN PN_GET",
        )
        self.assertIn("设置 SN（仅 FT1）", passage)
        self.assertIn("BURN_CHECK_PN（仅 FIT1）", passage)
        self.assertIn("PN_GET（仅 IQC）", passage)
        self.assertNotIn("Plug_DET", passage)
        self.assertNotIn("检查电流", passage)

    def test_passage_selection_does_not_split_composite_identifiers(self):
        module = load_module()
        query_tokens = module._passage_query_tokens("SN_MATCH_FAN_DET SET_PN")
        self.assertEqual(module._passage_line_score("M2_AUTO covers FAN", query_tokens), 0)
        self.assertEqual(module._passage_line_score("check Plug_DET", query_tokens), 0)
        self.assertGreater(
            module._passage_line_score("SN_MATCH_FAN_DET（仅 FIT1）", query_tokens), 0
        )

    def test_code_comments_are_not_treated_as_markdown_sections(self):
        module = load_module()
        content = (
            "# Guide\n" + "intro\n" * 500
            + "```bash\n# rkrag_cli ready example\necho wrong\n```\n"
            + "## Verify rkrag_cli\n"
            + "curl --unix-socket /tmp/rkrag_cli.sock http://localhost/status\n"
            + "ready means the service is available\n"
        )
        passage = module._best_passage(content, "rkrag_cli unix socket ready")
        self.assertIn("curl --unix-socket", passage)
        self.assertNotEqual(passage.strip(), "# rkrag_cli ready example")

    def test_heading_context_never_pushes_matched_line_out_of_passage(self):
        module = load_module()
        content = (
            "# Previous\n" + "old context\n" * 100
            + "## Validation\n" + "setup line\n" * 25
            + "curl --unix-socket /tmp/rkrag_cli.sock http://localhost/status\n"
            + '# expected: {"status":"ready"}\n'
            + "tail\n" * 100
        )
        with patch.dict("os.environ", {"RK_LEXICAL_PASSAGE_CHARS": "512"}):
            passage = module._best_passage(content, "unix socket ready status")
        self.assertTrue(passage.startswith("## Validation"))
        self.assertIn("curl --unix-socket /tmp/rkrag_cli.sock", passage)
        self.assertIn('"status":"ready"', passage)
        self.assertNotIn("old context", passage)

    def test_candidate_pool_never_shrinks_requested_top_k(self):
        module = load_module()
        self.assertGreaterEqual(module.retrieval_candidate_k(12), 12)
        self.assertGreaterEqual(
            module.retrieval_candidate_k(3, "Qwen2.5-7B的性能数据是多少？"), 12
        )

    def test_domain_query_expansion_adds_source_identifiers(self):
        module = load_module()
        value = json.dumps({
            "usb": ["USB_TEST", "CherryUSB ADB", "speed=5000", "timestamps:"],
            "ready": ["curl", "--unix-socket", "/tmp/rkrag_cli.sock", "http://localhost/status"],
            "复现": [
                "device.inf", "rkauth_tool_bin", "key.lic", "deploy_rkrag.sh",
                "run.sh", "run_server.sh", "/userdata/rkrag_cli/rag_model/",
            ],
        })
        with patch.dict("os.environ", {"RK_LEXICAL_QUERY_EXPANSIONS": value}):
            expanded = module._expand_query("FT测试中USB错误是为什么？")
            ready_expanded = module._expand_query("怎么查看服务是否 ready？")
            reproduction_expanded = module._expand_query("项目怎么复现？")
        self.assertIn("USB_TEST", expanded)
        self.assertIn("speed=5000", expanded)
        self.assertIn("--unix-socket", ready_expanded)
        self.assertIn("/tmp/rkrag_cli.sock", ready_expanded)
        self.assertIn("deploy_rkrag.sh", reproduction_expanded)
        self.assertIn("run_server.sh", reproduction_expanded)
        self.assertIn("device.inf", reproduction_expanded)
        self.assertIn("key.lic", reproduction_expanded)

    def test_invalid_query_expansion_is_ignored(self):
        module = load_module()
        with patch.dict("os.environ", {"RK_LEXICAL_QUERY_EXPANSIONS": "not-json"}):
            self.assertEqual(module._expand_query("USB问题"), "USB问题")

    def test_focused_passage_survives_mixed_merge_deduplication(self):
        module = load_module()
        merged = [{"chunk_id": "same", "content": "full " * 1000, "file_path": "ft.md"}]
        vector = [{
            "chunk_id": "same",
            "content": "# USB_TEST\nspeed=5000",
            "file_path": "ft.md",
            "lexical_score": 12.5,
            "rrf_score": 0.04,
            "lexical_rank": 1,
            "retrieval_rank": 2,
        }]
        restored = module.preserve_focused_evidence(merged, vector)
        self.assertEqual(restored, 1)
        self.assertEqual(merged[0]["content"], "# USB_TEST\nspeed=5000")
        self.assertEqual(merged[0]["source_type"], "lexical-fused")
        self.assertEqual(merged[0]["lexical_score"], 12.5)
        self.assertEqual(merged[0]["lexical_rank"], 1)
        self.assertEqual(merged[0]["retrieval_rank"], 2)

    def test_query_profile_soft_routes_exact_and_semantic_queries(self):
        module = load_module()
        self.assertEqual(
            module.query_retrieval_profile("burn_stress版本如何输出"), "exact"
        )
        self.assertEqual(
            module.query_retrieval_profile("IS6608A 和 MPQ8655 的电流基准是多少"),
            "exact",
        )
        self.assertEqual(
            module.query_retrieval_profile("介绍一下压力测试的整体原理"),
            "semantic",
        )
        self.assertEqual(module.query_retrieval_profile("USB错误是为什么"), "balanced")

        exact_profile, exact_vector, exact_lexical = module.query_aware_rrf_weights(
            "burn_stress版本如何输出"
        )
        self.assertEqual(exact_profile, "exact")
        self.assertGreater(exact_lexical, exact_vector)

    def test_exact_query_expands_rerank_window_and_protects_lexical_top_one(self):
        module = load_module()
        chunks = [
            {
                "chunk_id": "revision",
                "content": "# burn_stress 使用说明\n版本修订记录和作者信息",
                "rerank_score": 0.99,
                "retrieval_rank": 1,
                "lexical_rank": 2,
            },
            {
                "chunk_id": "command",
                "content": "## 版本检查\n```\nburn_stress -V\n```\nversion=V1.0.4",
                "rerank_score": 0.20,
                "retrieval_rank": 2,
                "lexical_rank": 1,
            },
            {
                "chunk_id": "summary",
                "content": "burn_stress运行在MSH环境，执行多项压力测试",
                "rerank_score": 0.80,
                "retrieval_rank": 3,
                "lexical_rank": 3,
            },
        ]

        self.assertEqual(
            module.query_aware_rerank_top_n(
                "burn_stress版本如何输出", chunks, requested_top_k=1
            ),
            3,
        )
        result = module.fuse_query_aware_rerank(
            "burn_stress版本如何输出", chunks, requested_top_k=1
        )
        self.assertEqual([item["chunk_id"] for item in result], ["command"])
        self.assertTrue(result[0]["exact_retrieval_protected"])

    def test_exact_protection_prefers_named_evidence_over_generic_lexical_top(self):
        module = load_module()
        chunks = [
            {
                "chunk_id": "generic-performance",
                "content": "性能测试章节说明，包含多个模型与通用指标。",
                "rerank_score": 0.99,
                "retrieval_rank": 1,
                "lexical_rank": 1,
            },
            {
                "chunk_id": "qwen-row",
                "content": (
                    "LLM Model Performance\n"
                    "ModelName TTFT TPS\n"
                    "Qwen2.5-7B 162.25ms 70.47"
                ),
                "rerank_score": 0.30,
                "retrieval_rank": 2,
                "lexical_rank": 2,
            },
        ]

        result = module.fuse_query_aware_rerank(
            "Qwen2.5-7B的性能数据是多少？", chunks, requested_top_k=1
        )

        self.assertEqual([item["chunk_id"] for item in result], ["qwen-row"])
        self.assertTrue(result[0]["exact_retrieval_protected"])
        self.assertEqual(result[0]["exact_evidence_coverage"], 1)
        self.assertIn("qwen2.5-7b", result[0]["exact_evidence_identifiers"])

    def test_exact_protection_uses_full_content_when_passage_was_clipped(self):
        module = load_module()
        chunks = [
            {
                "chunk_id": "table",
                "content": "性能说明（型号行已被窗口裁掉）",
                "full_content": "LLM Model Performance Qwen3-4B TTFT 109.78 TPOT 11.30 TPS 88.47",
                "rerank_score": 0.20,
                "retrieval_rank": 1,
                "lexical_rank": 2,
            },
            {
                "chunk_id": "generic",
                "content": "Qwen 模型性能概览",
                "full_content": "Qwen 模型性能概览",
                "rerank_score": 0.90,
                "retrieval_rank": 2,
                "lexical_rank": 1,
            },
        ]
        result = module.fuse_query_aware_rerank(
            "Qwen3-4B的性能数据是多少？", chunks, requested_top_k=1
        )
        self.assertEqual(result[0]["chunk_id"], "table")
        self.assertTrue(result[0]["exact_retrieval_protected"])


if __name__ == "__main__":
    unittest.main()
