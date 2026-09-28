from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "webui" / "query-status-banner.js"
READER = Path(__file__).parents[1] / "webui" / "reference-reader.js"


class WebUiDefaultsTest(unittest.TestCase):
    def test_one_time_mix_defaults_are_bounded(self):
        source = SCRIPT.read_text()
        self.assertIn("rk3588-rag-defaults-mix-v2", source)
        self.assertIn("mode: 'mix'", source)
        self.assertIn("top_k: 6", source)
        self.assertIn("chunk_top_k: 3", source)
        self.assertIn("max_total_tokens: 3000", source)
        self.assertIn("enable_rerank: true", source)

    def test_reference_links_open_an_in_page_reader(self):
        source = READER.read_text()
        self.assertIn("/query/references/", source)
        self.assertIn("source_group_id", source)
        self.assertIn("searchParams.get('hits')", source)
        self.assertIn("link.closest('ul, ol')", source)
        self.assertIn("frame.src = openFull.href = viewUrl(reference.chunk_id)", source)
        self.assertIn("page.querySelector('header')?.remove()", source)
        self.assertNotIn("window.open", source)
        self.assertNotIn("innerHTML", source)


if __name__ == "__main__":
    unittest.main()
