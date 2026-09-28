import importlib.util
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
