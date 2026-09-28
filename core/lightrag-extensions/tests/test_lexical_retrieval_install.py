import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "install_lightrag_lexical_retrieval_hook.py"


def load_module():
    spec = importlib.util.spec_from_file_location("lexical_install_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class LexicalRetrievalInstallTest(unittest.TestCase):
    def test_upgrades_v1_to_query_aware_vector_candidate_count(self):
        module = load_module()
        source = (
            module.IMPORT_INSERT.replace(module.MARKER, module.OLD_MARKER)
            + "\n    candidate_top_k = retrieval_candidate_k(search_top_k)\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operate.py"
            path.write_text(source)
            module.install(path)
            installed = path.read_text()
        self.assertIn(module.MARKER, installed)
        self.assertNotIn(module.OLD_MARKER, installed)
        self.assertIn(
            "candidate_top_k = retrieval_candidate_k(search_top_k, query)",
            installed,
        )


if __name__ == "__main__":
    unittest.main()
