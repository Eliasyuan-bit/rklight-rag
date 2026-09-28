import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


MODULE_PATH = Path(__file__).parents[1] / "rk_chunk_budget.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rk_chunk_budget_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class CharacterTokenizer:
    def encode(self, text):
        return list(text)

    def truncate_by_token_limit(self, text, limit):
        return SimpleNamespace(end=min(len(text), limit))


def generate_references(chunks):
    updated = []
    for chunk in chunks:
        item = chunk.copy()
        item["reference_id"] = "1"
        updated.append(item)
    return [{"reference_id": "1", "file_path": "guide.md"}], updated


def render_chunks(chunks):
    return "REF=1;" + chunks[0]["content"]


class ChunkBudgetTest(unittest.TestCase):
    def test_clips_top_evidence_to_exact_rendered_budget(self):
        module = load_module()
        result = module.fit_first_evidence_chunk(
            [{"chunk_id": "a", "file_path": "guide.md", "content": "x" * 100}],
            20,
            CharacterTokenizer(),
            generate_references,
            render_chunks,
        )
        self.assertEqual(len(result), 1)
        _, rendered = generate_references(result)
        self.assertLessEqual(len(render_chunks(rendered)), 20)
        self.assertGreater(len(result[0]["content"]), 0)

    def test_returns_empty_when_metadata_alone_exceeds_budget(self):
        module = load_module()
        result = module.fit_first_evidence_chunk(
            [{"content": "answer"}],
            3,
            CharacterTokenizer(),
            generate_references,
            render_chunks,
        )
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
