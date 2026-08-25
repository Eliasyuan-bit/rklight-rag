import importlib.util
import sys
from pathlib import Path


MODULE = Path(__file__).parents[1] / "route_markdown.py"
SPEC = importlib.util.spec_from_file_location("router", MODULE)
router = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules["router"] = router
SPEC.loader.exec_module(router)


def test_routes_tables_code_and_revision_to_text_only():
    blocks = router.parse_markdown(
        """# 正文\n\n这是模块关系和故障原因说明。\n\n## 修订记录\n\n| 版本 | 日期 |\n| --- | --- |\n| 1.0 | 今天 |\n\n## 处理\n\n```bash\necho test\n```\n\n请检查供电。\n"""
    )
    assert [block.kind for block in blocks] == ["kg", "text", "text", "kg"]
    assert "这是模块关系" in router.render(blocks, "kg", "source.md")
    text = router.render(blocks, "text", "source.md")
    assert "| 版本" in text
    assert "echo test" in text
