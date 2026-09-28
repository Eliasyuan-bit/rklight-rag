from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "webui" / "query-status-banner.js"


class WebUiDefaultsTest(unittest.TestCase):
    def test_one_time_mix_defaults_are_bounded(self):
        source = SCRIPT.read_text()
        self.assertIn("rk3588-rag-defaults-mix-v2", source)
        self.assertIn("mode: 'mix'", source)
        self.assertIn("top_k: 6", source)
        self.assertIn("chunk_top_k: 3", source)
        self.assertIn("max_total_tokens: 3000", source)
        self.assertIn("enable_rerank: true", source)


if __name__ == "__main__":
    unittest.main()
