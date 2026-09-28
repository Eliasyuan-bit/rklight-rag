import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "chunk_citation_install", ROOT / "install_lightrag_chunk_citation_hook.py"
)
installer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(installer)


class ChunkCitationInstallTest(unittest.TestCase):
    def test_upgrades_v1_reference_schema_with_evidence_location(self):
        source = (
            "    section: Optional[str] = Field(\n"
            "        default=None,\n"
            "        description=\"Markdown section containing the evidence\",\n"
            "    )\n"
            f"    {installer.OLD_ROUTES_MARKER}\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "query_routes.py"
            target.write_text(source, encoding="utf-8")
            installer.install_routes(target)
            installed = target.read_text(encoding="utf-8")
        self.assertIn("evidence_location: Optional[str]", installed)
        self.assertIn(installer.ROUTES_MARKER, installed)
        self.assertNotIn(installer.OLD_ROUTES_MARKER, installed)


if __name__ == "__main__":
    unittest.main()
