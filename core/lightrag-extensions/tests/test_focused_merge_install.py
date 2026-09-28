import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "install_lightrag_focused_merge_hook.py"


def load_module():
    spec = importlib.util.spec_from_file_location("focused_merge_hook_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class FocusedMergeInstallTest(unittest.TestCase):
    def test_fresh_install_adds_mix_caps(self):
        module = load_module()
        source = module.IMPORT_ANCHOR + module.CAP_ANCHOR + module.MERGE_ANCHOR
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operate.py"
            path.write_text(source)
            module.install(path)
            installed = path.read_text()
        self.assertIn(module.MARKER, installed)
        self.assertIn("bound_mix_graph_chunks", installed)
        self.assertIn("Mix graph chunk cap", installed)
        self.assertIn("focused restored", installed)

    def test_upgrades_v1_without_reinstalling_merge_logic(self):
        module = load_module()
        source = module.IMPORT_ANCHOR + module.OLD_IMPORT + module.CAP_ANCHOR
        source += module.MERGE_INSERT
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operate.py"
            path.write_text(source)
            module.install(path)
            installed = path.read_text()
        self.assertIn(module.MARKER, installed)
        self.assertNotIn(module.OLD_MARKER, installed)
        self.assertEqual(installed.count("Mix graph chunk cap"), 1)
        self.assertEqual(installed.count("restored_focused ="), 1)


if __name__ == "__main__":
    unittest.main()
