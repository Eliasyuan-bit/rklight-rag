import importlib.util
import asyncio
from pathlib import Path
import sys
import types
import unittest


MODULE_PATH = Path(__file__).parents[1] / "rk_reference_preview.py"


def load_module():
    markdown = types.ModuleType("lightrag.rk_reference_markdown")
    markdown.display_source_name = lambda path: Path(path).name.replace(".kg.md", ".md").replace(".text.md", ".md")
    sys.modules.setdefault("lightrag", types.ModuleType("lightrag"))
    sys.modules["lightrag.rk_reference_markdown"] = markdown
    spec = importlib.util.spec_from_file_location("rk_reference_preview_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class ReferencePreviewTest(unittest.TestCase):
    def test_validates_opaque_chunk_ids(self):
        module = load_module()
        self.assertTrue(module.valid_chunk_id("doc-a123-chunk-000"))
        self.assertFalse(module.valid_chunk_id("../../etc/passwd"))
        self.assertFalse(module.valid_chunk_id("chunk/id"))

    def test_builds_bounded_preview_with_section(self):
        module = load_module()
        preview = module.build_reference_preview(
            "doc-a-chunk-000",
            {"file_path": "guide.text.md", "content": "## Verify\ncommand\n"},
        )
        self.assertEqual(preview["display_name"], "guide.md")
        self.assertEqual(preview["section"], "Verify")
        self.assertEqual(preview["content"], "## Verify\ncommand\n")
        self.assertFalse(preview["truncated"])

    def test_limits_preview_size(self):
        module = load_module()
        preview = module.build_reference_preview(
            "doc-a-chunk-000", {"file_path": "a.md", "content": "x" * 25_000}
        )
        self.assertEqual(len(preview["content"]), module.MAX_PREVIEW_CHARS)
        self.assertTrue(preview["truncated"])

    def test_groups_two_routes_by_upload_not_filename_alone(self):
        module = load_module()
        kg = module.build_reference_preview(
            "doc-a-chunk-000", {"file_path": "guide.kg.md", "full_doc_id": "doc-a"},
            {"track_id": "upload-1"},
        )
        text = module.build_reference_preview(
            "doc-b-chunk-000", {"file_path": "guide.text.md", "full_doc_id": "doc-b"},
            {"track_id": "upload-1"},
        )
        later_upload = module.build_reference_preview(
            "doc-c-chunk-000", {"file_path": "guide.kg.md", "full_doc_id": "doc-c"},
            {"track_id": "upload-2"},
        )
        self.assertEqual(kg["source_group_id"], text["source_group_id"])
        self.assertNotEqual(kg["source_group_id"], later_upload["source_group_id"])

    def test_footer_group_resolves_upload_identity_without_changing_evidence(self):
        module = load_module()
        class Store:
            def __init__(self, values):
                self.values = values
            async def get_by_id(self, key):
                return self.values.get(key)
        rag = types.SimpleNamespace(
            text_chunks=Store({
                "chunk-a": {"file_path": "guide.kg.md", "full_doc_id": "doc-a"},
                "chunk-b": {"file_path": "guide.text.md", "full_doc_id": "doc-b"},
                "chunk-c": {"file_path": "guide.kg.md", "full_doc_id": "doc-c"},
            }),
            doc_status=Store({
                "doc-a": {"track_id": "upload-1"},
                "doc-b": {"track_id": "upload-1"},
                "doc-c": {"track_id": "upload-2"},
            }),
        )
        references = [
            {"reference_id": str(i), "chunk_id": chunk_id, "file_path": "guide.md"}
            for i, chunk_id in enumerate(("chunk-a", "chunk-b", "chunk-c"), 1)
        ]
        grouped = asyncio.run(module.group_footer_references(references, rag))
        self.assertEqual(grouped[0]["source_group_id"], grouped[1]["source_group_id"])
        self.assertNotEqual(grouped[0]["source_group_id"], grouped[2]["source_group_id"])
        self.assertNotIn("source_group_id", references[0])

    def test_renders_full_markdown_and_highlights_exact_passage(self):
        module = load_module()
        html = module.render_reference_document(
            "doc-a-chunk-001",
            {"file_path": "guide.kg.md", "content": "## Setup\n\nRun `start`."},
            {"file_path": "guide.kg.md", "content": "# Guide\n\n## Setup\n\nRun `start`.\n\n## Done\n"},
        )
        self.assertIn("<title>guide.md · 引用</title>", html)
        self.assertIn('id="cited-passage"', html)
        self.assertIn("<h2>Setup</h2>", html)
        self.assertIn("<h2>Done</h2>", html)
        self.assertIn('border-left:3px solid var(--cite-line)', html)
        self.assertIn(':root.rk-dark', html)
        self.assertNotIn('#fff8c5', html)

    def test_escapes_embedded_html_and_metadata(self):
        module = load_module()
        html = module.render_reference_document(
            "doc-a-chunk-001",
            {"file_path": '<img src=x onerror="alert(1)">.md', "content": "<script>x</script>"},
            {"content": "# Safe\n\n<script>x</script>"},
        )
        self.assertNotIn("<script>x</script>", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", html)

    def test_reader_hides_internal_source_comment_without_enabling_html(self):
        module = load_module()
        html = module.render_reference_document(
            "doc-a-chunk-000",
            {"file_path": "guide.text.md", "content": "<!-- source: guide.md; route: text-only -->\n# Setup\n\nRun it."},
            {"content": "<!-- source: guide.md; route: text-only -->\n# Setup\n\nRun it."},
        )
        self.assertNotIn("source: guide.md; route:", html)
        self.assertIn("<h1>Setup</h1>", html)


if __name__ == "__main__":
    unittest.main()
