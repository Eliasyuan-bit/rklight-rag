import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ingest_model_mode_install", ROOT / "install_lightrag_ingest_model_mode_hook.py"
)
installer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(installer)


class IngestModelModeInstallTest(unittest.TestCase):
    def test_wraps_one_pipeline_run_and_is_idempotent(self):
        source = f'''import uuid

class Pipeline:
    async def process(self):
        uncommitted_wakeup = False
        ingress = None
        try:
            {installer.BEGIN_ANCHOR.rstrip()}
                break
        finally:
            async def _finalize():
                pass

            await run_to_completion(_finalize)
'''
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pipeline.py"
            target.write_text(source, encoding="utf-8")
            source = installer.replace_once(
                source, installer.IMPORT_ANCHOR, installer.IMPORT_INSERT, "import anchor"
            )
            source = installer.replace_once(
                source, installer.STATE_ANCHOR, installer.STATE_INSERT, "state anchor"
            )
            source = installer.replace_once(
                source, installer.BEGIN_ANCHOR, installer.BEGIN_INSERT, "begin anchor"
            )
            source = installer.replace_once(
                source, installer.END_ANCHOR, installer.END_INSERT, "finalize anchor"
            )
            target.write_text(source, encoding="utf-8")

            installed = target.read_text(encoding="utf-8")
            self.assertIn("await enter_ingest_model_mode()", installed)
            self.assertIn("await run_to_completion(leave_ingest_model_mode)", installed)
            self.assertLess(
                installed.index("await run_to_completion(leave_ingest_model_mode)"),
                installed.index("await run_to_completion(_finalize)"),
            )
            self.assertIn("restoring query LLM", installed)
            self.assertIn(
                "query llm, reranker, and embedding models are ready",
                installed.lower(),
            )
            self.assertIn("Document indexing completed", installed)
            self.assertEqual(installed.count(installer.MARKER.strip()), 1)

    def test_upgrades_v1_finalize_ordering(self):
        source = (
            "import uuid\n"
            + installer.OLD_MARKER
            + installer.OLD_END_INSERT
        )
        source = installer.replace_once(
            source, installer.OLD_MARKER, installer.MARKER, "v1 marker"
        )
        source = installer.replace_once(
            source,
            installer.OLD_END_INSERT,
            installer.END_INSERT,
            "v1 finalize ordering",
        )
        self.assertNotIn(installer.OLD_END_INSERT, source)
        self.assertLess(
            source.index("await run_to_completion(leave_ingest_model_mode)"),
            source.index("await run_to_completion(_finalize)"),
        )

    def test_upgrades_v2_completion_message(self):
        source = "import uuid\n" + installer.V2_MARKER + installer.V2_END_INSERT
        source = installer.replace_once(
            source, installer.V2_MARKER, installer.MARKER, "v2 marker"
        )
        source = installer.replace_once(
            source,
            installer.V2_END_INSERT,
            installer.END_INSERT,
            "v2 completion message",
        )
        self.assertIn("Document indexing completed", source)
        self.assertNotIn(installer.V2_MARKER, source)
