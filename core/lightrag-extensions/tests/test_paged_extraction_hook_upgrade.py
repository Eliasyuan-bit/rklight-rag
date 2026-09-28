import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "install_lightrag_paged_extraction_hook",
    ROOT / "install_lightrag_paged_extraction_hook.py",
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


class PagedExtractionHookUpgradeTest(unittest.TestCase):
    def test_generated_async_block_is_valid_python(self):
        compile(
            "class Extractor:\n    async def extract_chunk(self):\n"
            + module.BLOCK_REPLACEMENT
            + "        pass\n",
            "<paged-extraction-block>",
            "exec",
        )

    def test_upgrade_replaces_v1_block_without_touching_prompt(self):
        old_block = (
            module.INSTALLED_BLOCK_START
            + "        old_pagination_behavior = True\n"
        )
        source = (
            module.OLD_MARKERS[0]
            + "\n"
            + old_block
            + module.BLOCK_END
            + "        untouched = True\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            operate = Path(directory) / "operate.py"
            prompt = Path(directory) / "prompt.py"
            operate.write_text(source, encoding="utf-8")
            prompt.write_text("existing prompt", encoding="utf-8")

            module.install(operate, prompt)
            upgraded = operate.read_text(encoding="utf-8")
            self.assertIn(module.MARKER, upgraded)
            self.assertIn("MAX_EXTRACTION_PAGES_PER_WINDOW", upgraded)
            self.assertIn("window_page_no = 0", upgraded)
            self.assertNotIn("old_pagination_behavior", upgraded)
            self.assertIn("untouched = True", upgraded)
            self.assertEqual(prompt.read_text(encoding="utf-8"), "existing prompt")

            module.install(operate, prompt)
            self.assertEqual(operate.read_text(encoding="utf-8"), upgraded)


if __name__ == "__main__":
    unittest.main()
