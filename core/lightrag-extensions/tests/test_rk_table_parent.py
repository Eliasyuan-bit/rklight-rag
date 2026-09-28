import importlib.util
from pathlib import Path
import sys
import unittest
import tempfile
import json


MODULE_PATH = Path(__file__).parents[1] / "rk_table_parent.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rk_table_parent_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class TableParentTest(unittest.TestCase):
    def test_llm_table_keeps_title_header_and_rows(self):
        module = load_module()
        content = (
            "LLM Model Performance\n"
            "Model Name Accelerator Input Tokens New Tokens TTFT TPOT Decode TPS\n"
            "Qwen2.5-7B RK1828 128 128 162.25 14.19 70.47\n"
            "Qwen3-4B RK1828 128 128 109.78 11.30 88.47\n"
        )
        result = module.expand_table_parent(
            "Qwen3-4B性能数据是多少",
            {"chunk_id": "pdf-chunk-004", "content": content},
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["table_type"], "llm_performance")
        self.assertIn("LLM Model Performance", result["content"])
        self.assertNotIn("Qwen2.5-7B", result["content"])
        self.assertIn("Qwen3-4B", result["content"])
        self.assertIn("- Model Name = Qwen3-4B", result["content"])
        self.assertIn("- TTFT (ms) = 109.78", result["content"])
        self.assertIn("- Decode TPS = 88.47", result["content"])
        self.assertTrue(result["table_evidence_valid"])
        self.assertEqual(result["table_row_records"][0]["fields"]["TTFT (ms)"], "109.78")

    def test_accuracy_table_renders_labelled_fields_for_matching_model(self):
        module = load_module()
        content = (
            "LLM Model Performance\n"
            "Acc (float32) Acc (W4A16 G32)\n"
            "Qwen2.5-0.5B RK182X gsm8k 40.71 36.09\n"
            "Qwen2.5-3B RK182X gsm8k 79.91 80.67\n"
            "Qwen3-4B RK1828 gsm8k 90.6 89.84\n"
        )
        result = module.expand_table_parent(
            "Qwen3-4B 在 RK1828 上的 gsm8k 精度是多少",
            {"chunk_id": "pdf-chunk-005", "content": content},
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["table_type"], "accuracy")
        self.assertNotIn("Qwen2.5-0.5B", result["content"])
        self.assertIn("- Acc (float32) = 90.6", result["content"])
        self.assertIn("- Acc (RKNN3 W4A16 G32) = 89.84", result["content"])
        self.assertEqual(
            result["table_row_records"][0]["fields"]["Acc (RKNN3 W4A16 G32)"], "89.84"
        )

    def test_server_config_table_parses_model_cpu_ram_ssd_and_time(self):
        module = load_module()
        content = (
            "LLM Model Performance\n"
            "Model Name Recommended Server Configurations Estimated Conversion Time\n"
            "Qwen 2.5 3B 32-core CPU / 32 GB RAM / 1 TB SSD/HDD ~52 minutes\n"
            "Qwen 2.5 7B 32-core CPU / 64 GB RAM / 1 TB SSD/HDD ~105 minutes\n"
        )
        result = module.expand_table_parent(
            "转换 Qwen2.5-7B 推荐什么服务器配置",
            {"chunk_id": "pdf-chunk-013", "content": content},
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["table_type"], "server_config")
        self.assertNotIn("Qwen 2.5 3B", result["content"])
        fields = result["table_row_records"][0]["fields"]
        self.assertEqual(fields["Model Name"], "Qwen 2.5 7B")
        self.assertEqual(fields["CPU"], "32-core CPU")
        self.assertEqual(fields["RAM"], "64 GB RAM")
        self.assertEqual(fields["Estimated Time"], "~105 minutes")
        self.assertIn("- Estimated Time = ~105 minutes", result["content"])

    def test_vlm_table_is_not_used_for_llm_query(self):
        module = load_module()
        content = (
            "Full-Modal Model Performance\n"
            "Model Name Accelerator Vision Resolution Vision Time Decode TPS\n"
            "Qwen3-4B RK1828 392x392 1176 878\n"
        )
        self.assertIsNone(module.expand_table_parent("Qwen3-4B性能数据是多少", {"content": content}))
        result = module.expand_table_parent("Qwen3-4B视觉性能是多少", {"content": content})
        self.assertIsNotNone(result)
        self.assertEqual(result["table_type"], "vlm_performance")

    def test_pipe_table_has_atomic_parent(self):
        module = load_module()
        content = (
            "### LLM Model Performance\n"
            "| Model | TTFT | TPOT | Decode TPS |\n"
            "| --- | --- | --- | --- |\n"
            "| Qwen3-4B | 109.78 | 11.30 | 88.47 |\n"
        )
        tables = module.extract_table_parents(content, chunk_id="c")
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]["table_id"], "c-table-00")
        self.assertEqual(tables[0]["table_type"], "llm_performance")

    def test_build_index_persists_parent_and_children(self):
        module = load_module()
        builder_spec = importlib.util.spec_from_file_location(
            "build_table_parent_index_test", MODULE_PATH.parent / "build_table_parent_index.py"
        )
        builder = importlib.util.module_from_spec(builder_spec)
        sys.modules[builder_spec.name] = builder
        sys.path.insert(0, str(MODULE_PATH.parent))
        assert builder_spec.loader
        builder_spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "chunks.json"
            output = Path(directory) / "table_parent_index.json"
            source.write_text(json.dumps({"c": {"content": (
                "LLM Model Performance\nModel Name Input Tokens New Tokens TTFT TPOT Decode TPS\n"
                "Qwen3-4B RK1828 128 128 109.78 11.30 88.47"
            ), "file_path": "a.pdf"}}, ensure_ascii=False), encoding="utf-8")
            result = builder.build(source)
            output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(len(result["tables"]), 1)
            self.assertEqual(len(result["children"]), 1)
            self.assertEqual(result["tables"][0]["table_type"], "llm_performance")
            self.assertEqual(result["children"][0]["model_key"], "qwen34b")
            self.assertEqual(result["children"][0]["fields"]["TTFT (ms)"], "109.78")

    def test_body_values_do_not_turn_an_llm_table_into_server_config(self):
        module = load_module()
        self.assertEqual(
            module.classify_table_type(
                "LLM Model Performance",
                ["Model Name Input Tokens New Tokens TTFT TPOT Decode TPS"],
                "Qwen2.5-7B 32-core CPU 64 GB RAM 1 TB SSD",
            ),
            "llm_performance",
        )

    def test_typed_parent_is_reserved_before_rerank(self):
        module = load_module()
        chunks = [
            {"chunk_id": "ordinary", "content": "Qwen3-4B full-modal row"},
            {
                "chunk_id": "table",
                "table_parent": True,
                "table_type": "llm_performance",
                "content": "LLM Model Performance Qwen3-4B 109.78 11.30 88.47",
            },
            {
                "chunk_id": "vlm-table",
                "table_parent": True,
                "table_type": "vlm_performance",
                "content": "VLM Model Performance Qwen3-4B 1176",
            },
        ]
        result = module.prioritize_typed_table_parents(
            chunks, "Qwen3-4B 在 RK1828 上的 LLM 性能数据是多少？"
        )
        self.assertEqual([item["chunk_id"] for item in result], ["table"])

    def test_untyped_query_keeps_normal_candidates(self):
        module = load_module()
        chunks = [{"chunk_id": "a"}, {"chunk_id": "b", "table_parent": True}]
        self.assertEqual(module.prioritize_typed_table_parents(chunks, "介绍一下部署"), chunks)

    def test_table_id_recovers_type_when_merge_drops_metadata(self):
        module = load_module()
        chunks = [
            {
                "chunk_id": "pdf-chunk-004-table-00",
                "content": (
                    "LLM Model Performance\n"
                    "Model Name Input Tokens New Tokens TTFT TPOT Decode TPS\n"
                    "Qwen3-4B RK1828 128 128 109.78 11.30 88.47"
                ),
            },
            {
                "chunk_id": "pdf-chunk-004-table-01",
                "content": "VLM Model Performance\nModel Vision Time\nQwen3-4B 1176",
            },
        ]
        result = module.prioritize_typed_table_parents(chunks, "Qwen3-4B性能数据是多少")
        self.assertEqual([item["chunk_id"] for item in result], ["pdf-chunk-004-table-00"])
        self.assertEqual(result[0]["table_type"], "llm_performance")


if __name__ == "__main__":
    unittest.main()
