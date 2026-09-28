import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "rk_paged_extraction", ROOT / "rk_paged_extraction.py"
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


class PagedExtractionTest(unittest.TestCase):
    def test_continuation_conditions(self):
        self.assertTrue(
            module.extraction_needs_next_page("partial", truncated=True)
        )
        self.assertTrue(
            module.extraction_needs_next_page("row\n<|MORE|>", truncated=False)
        )
        self.assertTrue(module.extraction_needs_next_page("row", truncated=False))
        self.assertFalse(
            module.extraction_needs_next_page(
                "row\n<|COMPLETE|>", truncated=False
            )
        )

    def test_seen_summary_excludes_descriptions(self):
        nodes = {"RK1828": [{"description": "must not leak"}]}
        edges = {("RKNN3", "RK1828"): [{"description": "also secret"}]}
        result = module.build_seen_summary(nodes, edges)
        self.assertIn("RK1828", result)
        self.assertIn("RKNN3 -> RK1828", result)
        self.assertNotIn("must not leak", result)
        self.assertNotIn("also secret", result)

    def test_merge_counts_only_new_keys_and_keeps_better_description(self):
        target_nodes = {"A": [{"description": "short"}]}
        target_edges = {}
        added = module.merge_extraction_page(
            target_nodes,
            target_edges,
            {
                "A": [{"description": "a longer description"}],
                "B": [{"description": "new"}],
            },
            {("A", "B"): [{"description": "related"}]},
        )
        self.assertEqual(added, 2)
        self.assertEqual(target_nodes["A"][0]["description"], "a longer description")

    def test_continue_prompt_is_stateless_and_bounded(self):
        prompt = module.build_continue_prompt(
            input_text="RKNN3 supports RK1828.",
            heading_context_block="",
            seen_summary="Entities: RKNN3\nRelations: (none)",
            page_no=2,
            max_pages=4,
            window_no=2,
            window_count=3,
            max_total_records=12,
            max_entity_records=8,
            language="Chinese",
        )
        self.assertIn("page 2 of at most 4", prompt)
        self.assertIn("window 2 of 3", prompt)
        self.assertIn("RKNN3 supports RK1828.", prompt)
        self.assertIn("<|MORE|>", prompt)
        self.assertIn("<|COMPLETE|>", prompt)
        self.assertNotIn("assistant", prompt.lower())

    def test_split_extraction_windows_keeps_sentence_boundaries(self):
        text = "组件A连接组件B。组件C调用组件D。组件E管理组件F。"
        windows = module.split_extraction_windows(text, max_chars=80)
        self.assertEqual(windows, [text])

        long_text = text * 8
        windows = module.split_extraction_windows(long_text, max_chars=80)
        self.assertGreater(len(windows), 1)
        self.assertEqual("".join(windows), long_text)
        self.assertTrue(all(len(window) <= 80 for window in windows))

    def test_missing_marker_still_requests_one_audit_page(self):
        self.assertTrue(
            module.extraction_needs_next_page("one complete record", truncated=False)
        )


if __name__ == "__main__":
    unittest.main()
