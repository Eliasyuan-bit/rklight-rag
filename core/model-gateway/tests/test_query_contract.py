import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "rk1828_model_gateway.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rk1828_model_gateway_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class QueryContractTest(unittest.TestCase):
    def test_grounding_contract_is_near_generation_turn(self):
        module = load_module()
        original = [{"role": "user", "content": "context and question"}]
        prepared = module.prepare_query_messages(original)
        self.assertEqual(prepared[0]["role"], "system")
        self.assertIn("按原文抄写", prepared[0]["content"])
        self.assertIn("不得漏掉问题点名的对象", prepared[-1]["content"])
        self.assertEqual(original[0]["content"], "context and question")

    def test_contract_allows_all_required_comparison_items(self):
        module = load_module()
        self.assertNotIn("最多两项", module.QUERY_OUTPUT_SUFFIX)
        self.assertIn("不得漏掉问题点名的对象", module.QUERY_OUTPUT_SUFFIX)
        self.assertIn("不得跨标题取值", module.QUERY_OUTPUT_SUFFIX)

    def test_contract_enforces_scope_exceptions_and_freshness(self):
        module = load_module()
        self.assertIn("“仅X”事实只能归入X", module.QUERY_SYSTEM_PROMPT)
        self.assertIn("特定例外", module.QUERY_SYSTEM_PROMPT)
        self.assertIn("上下文无实时证据", module.QUERY_SYSTEM_PROMPT)

    def test_contract_uses_compact_intent_specific_formats(self):
        module = load_module()
        self.assertIn("禁止总结", module.QUERY_SYSTEM_PROMPT)
        self.assertIn("引用由系统统一追加", module.QUERY_OUTPUT_SUFFIX)
        self.assertNotIn("命令题", module.QUERY_SYSTEM_PROMPT)
        self.assertNotIn("原因题", module.QUERY_OUTPUT_SUFFIX)

    def test_extracts_lightrag_query_and_routes_one_intent_contract(self):
        module = load_module()
        content = "large context with 为什么\n\n---User Query---\n介绍一下项目怎么复现"
        query = module.extract_user_query(content)
        self.assertEqual(query, "介绍一下项目怎么复现")
        suffix = module.intent_output_suffix(query)
        self.assertIn("1. 环境", suffix)
        self.assertIn("5. 启动验证", suffix)
        self.assertIn("原文启动命令及验证方式", suffix)
        self.assertNotIn("本题格式：原因", suffix)

    def test_reason_contract_does_not_force_three_items(self):
        module = load_module()
        suffix = module.intent_output_suffix("USB 错误是为什么？")
        self.assertIn("一至三条", suffix)
        self.assertIn("不为凑数", suffix)

    def test_comparison_contract_forbids_repeated_summary(self):
        module = load_module()
        suffix = module.intent_output_suffix("FT1 和 IQC 有什么区别？")
        self.assertIn("每个点名对象只写一个单行列表项", suffix)
        self.assertIn("不得换一种说法重复", suffix)

    def test_realtime_contract_takes_priority_over_cause_words(self):
        module = load_module()
        suffix = module.intent_output_suffix("我现在这块板的 USB 错误是不是线坏了？")
        self.assertIn("只输出两句", suffix)
        self.assertNotIn("一至三条", suffix)

    def test_error_classification_is_not_routed_as_a_cause_question(self):
        module = load_module()
        suffix = module.intent_output_suffix("date 没有时间戳应归类为什么错误？")
        self.assertIn("错误类别", suffix)
        self.assertNotIn("一至三条", suffix)

    def test_generic_how_to_uses_non_repeating_steps(self):
        module = load_module()
        suffix = module.intent_output_suffix("怎么定位测试过程？")
        self.assertIn("操作步骤", suffix)
        self.assertIn("不重复", suffix)

    def test_performance_how_question_is_not_misclassified_as_steps(self):
        module = load_module()
        suffix = module.intent_output_suffix("qwen2.5-7B的性能如何")
        self.assertEqual(suffix, "")

    def test_explicit_model_metric_query_uses_local_keywords(self):
        module = load_module()
        prompt = """---Role---
You are an expert keyword extractor.
---Real Data---
User Query: 请给出Qwen3-4B在RK1828上的Input Tokens、TTFT和TPOT数值。
---Output---
Output:"""
        result = module.fast_metric_keywords([{"role": "user", "content": prompt}])
        self.assertIsNotNone(result)
        payload = module.json.loads(result)
        self.assertEqual(
            payload["low_level_keywords"],
            ["Qwen3-4B", "RK1828", "Input Tokens", "TTFT", "TPOT"],
        )
        self.assertIn("model performance", payload["high_level_keywords"])

    def test_non_metric_keyword_query_keeps_llm_path(self):
        module = load_module()
        prompt = """You are an expert keyword extractor.
---Real Data---
User Query: FT测试中USB错误是为什么？
---Output---"""
        self.assertIsNone(
            module.fast_metric_keywords([{"role": "user", "content": prompt}])
        )

    def test_location_plus_how_to_keeps_both_requested_dimensions(self):
        module = load_module()
        suffix = module.intent_output_suffix("日志在哪里，怎么定位过程？")
        self.assertIn("第一句回答位置", suffix)

    def test_same_rule_question_uses_one_general_exception_sentence(self):
        module = load_module()
        suffix = module.intent_output_suffix("重复授权不扣次数，加密狗方式也一样吗？")
        self.assertIn("只用一句话", suffix)

    def test_query_output_budget_uses_remaining_context(self):
        module = load_module()
        with patch.object(module, "LLM_CONTEXT_TOKENS", 1000), \
             patch.object(module, "QUERY_CONTEXT_RESERVE", 100):
            short = [{"role": "user", "content": "USB错误"}]
            long = [{"role": "user", "content": "中" * 800}]
            self.assertEqual(module.resolve_query_max_tokens(short, 512, 512), 512)
            self.assertLess(module.resolve_query_max_tokens(long, 512, 512), 100)

    def test_query_output_budget_never_exceeds_request_or_ceiling(self):
        module = load_module()
        messages = [{"role": "user", "content": "short"}]
        self.assertEqual(module.resolve_query_max_tokens(messages, 96, 512), 96)
        self.assertEqual(module.resolve_query_max_tokens(messages, 800, 320), 320)

    def test_strips_model_generated_reference_footer(self):
        module = load_module()
        answer = "USB检测失败。\n\n**引用**\n* [1] manual.text.md"
        self.assertEqual(module.strip_model_reference_footer(answer), "USB检测失败。")
        english = "Answer.\n### References\n- [1] guide.md"
        self.assertEqual(module.strip_model_reference_footer(english), "Answer.")

    def test_stream_filter_handles_reference_heading_split_across_tokens(self):
        module = load_module()
        output = []
        stream_filter = module.ModelReferenceFooterFilter(output.append)
        for token in ("USB检测失败。\n\n**引", "用", "**\n", "* [1] manual.md"):
            stream_filter.feed(token)
        stream_filter.finish()
        self.assertEqual("".join(output), "USB检测失败。")

    def test_stream_filter_flushes_normal_short_answer(self):
        module = load_module()
        output = []
        stream_filter = module.ModelReferenceFooterFilter(output.append)
        stream_filter.feed("正常短回答")
        stream_filter.finish()
        self.assertEqual("".join(output), "正常短回答")


if __name__ == "__main__":
    unittest.main()
