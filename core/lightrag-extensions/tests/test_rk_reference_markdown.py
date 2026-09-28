import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).parents[1] / "rk_reference_markdown.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rk_reference_markdown_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class ReferenceMarkdownTest(unittest.TestCase):
    def test_renders_chunk_level_reference_footer(self):
        module = load_module()
        footer = module.render_reference_markdown([
            {
                "reference_id": "1",
                "file_path": "/docs/guide.md",
                "section": "部署 > 验证",
                "chunk_id": "doc-a-chunk-003",
            }
        ])
        self.assertIn("### References", footer)
        self.assertIn(r"[\[1\] guide.md — 部署 > 验证]", footer)
        self.assertIn("/query/references/doc-a-chunk-003/view#cited-passage", footer)

    def test_skips_invalid_and_duplicate_reference_ids(self):
        module = load_module()
        footer = module.render_reference_markdown([
            {"reference_id": "1", "file_path": "a.md"},
            {"reference_id": "1", "file_path": "duplicate.md"},
            {"reference_id": "2", "file_path": ""},
        ])
        self.assertEqual(footer.count("- [1] a.md"), 1)
        self.assertNotIn("duplicate.md", footer)
        self.assertNotIn("- [2]", footer)

    def test_empty_references_have_no_footer(self):
        module = load_module()
        self.assertEqual(module.render_reference_markdown([]), "")

    def test_one_footer_line_per_upload_with_all_cited_chunk_ids(self):
        module = load_module()
        footer = module.render_reference_markdown([
            {"reference_id": "1", "file_path": "guide.kg.md", "chunk_id": "doc-a-chunk-000", "source_group_id": "upload-1:guide.md"},
            {"reference_id": "2", "file_path": "guide.text.md", "chunk_id": "doc-b-chunk-000", "source_group_id": "upload-1:guide.md"},
            {"reference_id": "3", "file_path": "guide.kg.md", "chunk_id": "doc-c-chunk-000", "source_group_id": "upload-2:guide.md"},
        ])
        self.assertEqual(footer.count("- ["), 2)
        self.assertIn("guide.md · 2 处命中", footer)
        self.assertIn("/view?hits=doc-b-chunk-000#cited-passage", footer)
        self.assertIn("/query/references/doc-c-chunk-000/view#cited-passage", footer)

    def test_hides_ingestion_variant_suffixes_from_display_name(self):
        module = load_module()
        footer = module.render_reference_markdown([
            {"reference_id": "1", "file_path": "/docs/工程部署指南.kg.md"},
            {"reference_id": "2", "file_path": "/docs/1820_test.text.md"},
            {"reference_id": "3", "file_path": "/docs/manual.pdf"},
        ])
        self.assertIn("[1] 工程部署指南.md", footer)
        self.assertIn("[2] 1820_test.md", footer)
        self.assertIn("[3] manual.pdf", footer)
        self.assertNotIn(".kg.md", footer)
        self.assertNotIn(".text.md", footer)


if __name__ == "__main__":
    unittest.main()
