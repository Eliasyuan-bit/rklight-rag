import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "reference_location_install", ROOT / "install_lightrag_reference_location_hook.py"
)
installer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(installer)


class ReferenceLocationInstallTest(unittest.TestCase):
    def test_installs_at_both_final_response_boundaries(self):
        source = (
            installer.IMPORT_ANCHOR
            + "    def _build_stream_generator(\n"
            + installer.STREAM_SIGNATURE_ANCHOR
            + "    ):\n"
            + installer.NONSTREAM_ANCHOR
            + installer.STREAM_ANCHOR
            + installer.CALL_ANCHOR
            + installer.DEFAULT_CALL_ANCHOR
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "query_routes.py"
            target.write_text(source, encoding="utf-8")
            installer.install(target)
            installer.install(target)
            installed = target.read_text(encoding="utf-8")
        self.assertIn(installer.MARKER, installed)
        self.assertEqual(installed.count("enrich_reference_locations("), 2)
        self.assertEqual(installed.count("query=request.query,"), 2)


if __name__ == "__main__":
    unittest.main()
