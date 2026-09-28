import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "document_footer_install", ROOT / "install_lightrag_document_reference_footer_hook.py"
)
hook = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(hook)


class DocumentFooterInstallTest(unittest.TestCase):
    def test_patches_both_stream_paths_idempotently(self):
        source = (
            "from lightrag.rk_reference_preview import (\n"
            + hook.IMPORT_ANCHOR
            + ")\n"
            + hook.STREAM_ANCHOR + "\n"
            + hook.NONSTREAM_ANCHOR + "\n"
        )
        with tempfile.TemporaryDirectory() as temp:
            route = Path(temp) / "query_routes.py"
            route.write_text(source)
            hook.install(route)
            installed = route.read_text()
            self.assertIn("await group_footer_references(references, rag)", installed)
            self.assertEqual(installed.count("await group_footer_references"), 2)
            hook.install(route)
            self.assertEqual(route.read_text(), installed)


if __name__ == "__main__":
    unittest.main()
