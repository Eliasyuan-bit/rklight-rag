import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).parents[1] / "rk_chunk_citations.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rk_chunk_citations_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class ChunkCitationsTest(unittest.TestCase):
    def test_assigns_one_reference_per_chunk_from_same_file(self):
        module = load_module()
        references, chunks = module.generate_chunk_reference_list([
            {"chunk_id": "a", "file_path": "guide.md", "content": "# Start\nA"},
            {"chunk_id": "b", "file_path": "guide.md", "content": "## Verify\nB"},
        ])
        self.assertEqual([item["reference_id"] for item in references], ["1", "2"])
        self.assertEqual([item["chunk_id"] for item in references], ["a", "b"])
        self.assertEqual([item["section"] for item in references], ["Start", "Verify"])
        self.assertEqual([item["reference_id"] for item in chunks], ["1", "2"])

    def test_unknown_source_does_not_create_reference(self):
        module = load_module()
        references, chunks = module.generate_chunk_reference_list([
            {"chunk_id": "a", "file_path": "unknown_source", "content": "text"}
        ])
        self.assertEqual(references, [])
        self.assertEqual(chunks[0]["reference_id"], "")

    def test_preserves_selected_table_title_and_model_row_as_location(self):
        module = load_module()
        references, _ = module.generate_chunk_reference_list([{
            "chunk_id": "performance-table", "file_path": "release.pdf",
            "table_parent": True, "table_title": "LLM Model Performance",
            "table_row_records": [{
                "raw": "Qwen3-4B RK1828 128 128 109.78 11.30 88.47",
                "fields": {"Model Name": "Qwen3-4B"},
            }],
        }])
        self.assertEqual(
            references[0]["evidence_location"],
            "表格：LLM Model Performance；行：Qwen3-4B",
        )

    def test_recovers_table_location_from_final_chunk_and_query(self):
        module = load_module()
        table_spec = importlib.util.spec_from_file_location(
            "rk_table_parent", MODULE_PATH.parent / "rk_table_parent.py"
        )
        table_module = importlib.util.module_from_spec(table_spec)
        assert table_spec.loader
        sys.modules["rk_table_parent"] = table_module
        table_spec.loader.exec_module(table_module)
        references = [{"reference_id": "1", "file_path": "release.pdf"}]
        chunks = [{
            "reference_id": "1", "chunk_id": "performance-table",
            "content": (
                "LLM Model Performance\n"
                "Model Name Accelerator Input Tokens New Tokens TTFT TPOT Decode TPS\n"
                "Qwen3-4B RK1828 128 128 109.78 11.30 88.47"
            ),
        }]
        result = module.enrich_reference_locations(
            references, chunks, "Qwen3-4B 在 RK1828 上的性能数据是多少"
        )
        self.assertEqual(
            result[0]["evidence_location"],
            "表格：LLM Model Performance；行：Qwen3-4B",
        )


if __name__ == "__main__":
    unittest.main()
