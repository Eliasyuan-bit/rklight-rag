import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).parents[1] / "rk_section_parent.py"

def load_module():
    spec = importlib.util.spec_from_file_location("rk_section_parent_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module

class SectionParentTest(unittest.TestCase):
    def test_selects_named_sibling_without_neighbour_pollution(self):
        module = load_module()
        content = "### USB 自动测试\n查找 CherryUSB ADB，要求 speed=5000；date 输出必须含 local。\n\n### SET_PN 写入产品号\n进入 MaskRom 和 Loader。\n\n### SARADC 测试\n读取 raw 与 scale。\n"
        result = module.prioritize_section_parents([{"chunk_id": "manual-005", "content": content}], "USB 错误为什么发生？", {})
        self.assertTrue(result[0]["section_parent"])
        self.assertIn("CherryUSB", result[0]["content"])
        self.assertNotIn("SET_PN", result[0]["content"])
        self.assertNotIn("SARADC", result[0]["content"])

    def test_uses_same_algorithm_for_other_headings(self):
        module = load_module()
        content = "### Alpha procedure\nalpha start.\n### Beta procedure\nbeta start and finish.\n### Gamma procedure\ngamma start.\n"
        result = module.prioritize_section_parents([{"chunk_id": "manual-006", "content": content}], "Beta procedure 怎么执行？", {})
        self.assertEqual(result[0]["section_parent_heading"], "Beta procedure")
        self.assertNotIn("Gamma", result[0]["content"])

    def test_loads_original_source_for_short_lexical_candidate(self):
        module = load_module()
        content = "### USB 自动测试\nCherryUSB ADB speed=5000 local\n### SET_PN\nMaskRom Loader\n"
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "kv_store_text_chunks.json").write_text(json.dumps({"chunk-1": {"content": content, "heading": {"heading": "USB 自动测试"}}}, ensure_ascii=False), encoding="utf-8")
            result = module.prioritize_section_parents([{"chunk_id": "chunk-1", "content": "USB"}], "USB错误", {"working_dir": directory})
        self.assertIn("speed=5000", result[0]["content"])
        self.assertNotIn("SET_PN", result[0]["content"])

    def test_preserves_single_section_and_table_parent(self):
        module = load_module()
        chunk = {"chunk_id": "one", "content": "### Only\nOne body."}
        self.assertIs(module.prioritize_section_parents([chunk], "Only", {})[0], chunk)
        table = {"chunk_id": "table", "content": "### A\na\n### B\nb", "table_parent": True}
        self.assertIs(module.prioritize_section_parents([table], "A", {})[0], table)
