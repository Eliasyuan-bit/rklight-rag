import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "install_lightrag_query_default_hook.py"


def load_module():
    spec = importlib.util.spec_from_file_location("query_default_hook_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class QueryDefaultHookTest(unittest.TestCase):
    def test_upgrades_v1_with_environment_backed_user_prompt(self):
        module = load_module()
        source = module.INSERT.replace(module.MARKER, module.OLD_MARKERS[-1])
        source += "\n" + module.USER_PROMPT_ANCHOR
        source += "\n" + module.MIX_BUDGET_ANCHOR
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "query_routes.py"
            path.write_text(source)
            module.install(path)
            installed = path.read_text()
        self.assertIn(module.MARKER, installed)
        self.assertNotIn(module.OLD_MARKERS[-1], installed)
        self.assertIn('default=os.getenv("RK_DEFAULT_USER_PROMPT") or None', installed)
        self.assertIn('param.max_entity_tokens = 0', installed)

    def test_upgrades_v2_with_diagnostic_graph_budget(self):
        module = load_module()
        source = module.INSERT.replace(module.MARKER, module.OLD_MARKERS[0])
        source += "\n" + module.USER_PROMPT_INSERT
        source += "\n" + module.MIX_BUDGET_ANCHOR
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "query_routes.py"
            path.write_text(source)
            module.install(path)
            installed = path.read_text()
        self.assertIn(module.MARKER, installed)
        self.assertNotIn(module.OLD_MARKERS[0], installed)
        self.assertIn('param.max_relation_tokens = 0', installed)

    def test_upgrades_v3_with_exact_query_graph_suppression(self):
        module = load_module()
        source = module.INSERT.replace(module.MARKER, module.OLD_MARKERS[0])
        source += "\n" + module.USER_PROMPT_INSERT
        source += "\n" + module.MIX_BUDGET_V3
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "query_routes.py"
            path.write_text(source)
            module.install(path)
            installed = path.read_text()
        self.assertIn(module.MARKER, installed)
        self.assertNotIn(module.OLD_MARKERS[0], installed)
        self.assertIn("query_retrieval_profile(self.query)", installed)

    def test_upgrades_v4_with_document_fact_graph_suppression(self):
        module = load_module()
        old_insert = module.MIX_BUDGET_INSERT.replace(
            'or query_retrieval_profile(self.query)\n'
            '                in ("exact", "document_fact")',
            'or query_retrieval_profile(self.query) == "exact"',
        )
        source = module.INSERT.replace(module.MARKER, module.OLD_MARKERS[0])
        source += "\n" + module.USER_PROMPT_INSERT
        source += "\n" + old_insert
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "query_routes.py"
            path.write_text(source)
            module.install(path)
            installed = path.read_text()
        self.assertIn(module.MARKER, installed)
        self.assertIn('in ("exact", "document_fact")', installed)


if __name__ == "__main__":
    unittest.main()
