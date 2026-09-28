import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "relation_context_install", ROOT / "install_lightrag_relation_context_hook.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RelationContextInstallTest(unittest.TestCase):
    def test_installs_source_grounding_after_graph_retrieval(self):
        source = '''async def _build_context_str():
    tokenizer = global_config.get("tokenizer")
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operate.py"
            path.write_text(source)
            MODULE.install(path)
            installed = path.read_text()
        self.assertIn(MODULE.MARKER, installed)
        self.assertIn('query_retrieval_profile(query) == "relation_fact"', installed)
        self.assertIn("entities_context = []", installed)
        self.assertIn("relations_context = []", installed)


if __name__ == "__main__":
    unittest.main()
