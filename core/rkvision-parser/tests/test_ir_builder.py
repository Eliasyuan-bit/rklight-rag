from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "rkvision_lightrag" / "ir_builder.py"


@dataclass
class IRPosition:
    type: str
    anchor: Any = None
    range: list | None = None
    charspan: list[int] | None = None
    origin: str | None = None


@dataclass
class IRTable:
    placeholder_key: str
    rows: list[list[str]] | None = None
    html: str | None = None
    num_rows: int = 0
    num_cols: int = 0
    caption: str = ""
    footnotes: list[str] = field(default_factory=list)
    table_header: list[list[str]] | str | None = None


@dataclass
class IRBlock:
    content_template: str
    heading: str = ""
    level: int = 0
    parent_headings: list[str] = field(default_factory=list)
    is_title_block: bool = False
    positions: list[IRPosition] = field(default_factory=list)
    tables: list[IRTable] = field(default_factory=list)


@dataclass
class IRDoc:
    document_name: str
    document_format: str
    doc_title: str
    split_option: dict[str, Any]
    blocks: list[IRBlock]
    assets: list = field(default_factory=list)
    bbox_attributes: dict[str, Any] | None = None


def load_module():
    lightrag = types.ModuleType("lightrag")
    sidecar = types.ModuleType("lightrag.sidecar")
    ir = types.ModuleType("lightrag.sidecar.ir")
    ir.IRPosition = IRPosition
    ir.IRTable = IRTable
    ir.IRBlock = IRBlock
    ir.IRDoc = IRDoc
    modules = {
        "lightrag": lightrag,
        "lightrag.sidecar": sidecar,
        "lightrag.sidecar.ir": ir,
    }
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location("rkvision_ir_builder_test", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


def block(order, label, text, box, source="pdfium"):
    return {
        "reading_order": order,
        "label": label,
        "text": text,
        "box": box,
        "text_source": source,
    }


class RkVisionIRBuilderTests(unittest.TestCase):
    def test_preserves_heading_positions_and_reconstructs_table(self):
        module = load_module()
        document = {
            "page_count": 1,
            "pages": [
                {
                    "page": 1,
                    "blocks": [
                        block(0, "title", "USB 测试", [10, 10, 200, 40]),
                        block(1, "plain text", "以下为触发条件。", [10, 60, 300, 85]),
                        block(2, "table", "测试项", [10, 100, 100, 125]),
                        block(3, "table", "失败条件", [140, 100, 300, 125]),
                        block(4, "table", "USB", [10, 140, 100, 165]),
                        block(5, "table", "未找到 CherryUSB ADB", [140, 140, 350, 165]),
                    ],
                }
            ],
        }

        result = module.RkVisionIRBuilder().normalize(
            document, document_name="manual.pdf"
        )

        self.assertEqual(result.doc_title, "USB 测试")
        self.assertEqual(result.bbox_attributes, {"origin": "LEFTTOP"})
        self.assertEqual(len(result.blocks), 3)
        self.assertEqual(result.blocks[1].heading, "USB 测试")
        self.assertTrue(result.blocks[0].is_title_block)
        self.assertEqual(result.blocks[0].level, 0)
        self.assertEqual(result.blocks[1].positions[0].anchor, "1")
        table = result.blocks[2].tables[0]
        self.assertEqual(
            table.rows,
            [["测试项", "失败条件"], ["USB", "未找到 CherryUSB ADB"]],
        )
        self.assertEqual(table.table_header, [["测试项", "失败条件"]])

    def test_infers_numbered_heading_hierarchy(self):
        module = load_module()
        document = {
            "pages": [
                {
                    "page": 1,
                    "blocks": [
                        block(0, "title", "产品手册", [0, 0, 100, 20]),
                        block(1, "title", "2 使用说明", [0, 30, 100, 50]),
                        block(2, "title", "2.2 快速上手", [0, 60, 100, 80]),
                        block(3, "title", "2.2.1 设备授权", [0, 90, 100, 110]),
                        block(4, "plain text", "执行授权命令。", [0, 120, 100, 140]),
                    ],
                }
            ]
        }

        result = module.RkVisionIRBuilder().normalize(
            document, document_name="manual.pdf"
        )

        self.assertEqual([item.level for item in result.blocks[:4]], [0, 1, 2, 3])
        self.assertEqual(
            result.blocks[4].parent_headings,
            ["产品手册", "2 使用说明", "2.2 快速上手"],
        )
        self.assertEqual(result.blocks[4].heading, "2.2.1 设备授权")

    def test_keeps_list_heading_siblings_and_rejects_layout_noise(self):
        module = load_module()
        document = {
            "pages": [
                {
                    "blocks": [
                        block(0, "title", "产品手册", [0, 0, 10, 10]),
                        block(1, "title", "3 量产授权", [0, 20, 10, 30]),
                        block(2, "title", "1）生产时获取", [0, 40, 10, 50]),
                        block(3, "title", "2）出厂后获取", [0, 60, 10, 70]),
                        block(4, "title", "a) 预写激活码", [0, 80, 10, 90]),
                        block(5, "title", "b) 服务端分发", [0, 100, 10, 110]),
                        block(6, "title", "3）代理激活", [0, 120, 10, 130]),
                        block(7, "title", "参数：", [0, 140, 10, 150]),
                        block(8, "title", "◼ password：密码", [0, 160, 10, 170]),
                        block(9, "title", "_ _", [0, 180, 10, 190]),
                        block(10, "title", "2.3 详细说明........", [0, 200, 10, 210]),
                    ]
                }
            ]
        }

        result = module.RkVisionIRBuilder().normalize(
            document, document_name="manual.pdf"
        )

        headings = [item for item in result.blocks if item.content_template.startswith("#")]
        self.assertEqual(
            [item.level for item in headings], [0, 1, 2, 2, 3, 3, 2, 3]
        )
        self.assertEqual(result.blocks[-2].content_template, "◼ password：密码")
        self.assertEqual(result.blocks[-1].content_template, "2.3 详细说明........")

    def test_drops_ocr_figure_noise_but_preserves_native_text(self):
        module = load_module()
        document = {
            "pages": [
                {
                    "page": 2,
                    "blocks": [
                        block(0, "figure", "UI button", [1, 1, 5, 5], "ocr"),
                        block(1, "abandon", "native footer", [1, 10, 5, 15]),
                        block(2, "plain text", "body", [1, 20, 5, 25]),
                    ],
                }
            ]
        }

        result = module.RkVisionIRBuilder().normalize(
            document, document_name="manual.pdf"
        )

        contents = [item.content_template for item in result.blocks]
        self.assertEqual(contents, ["native footer", "body"])

    def test_rejects_document_without_usable_blocks(self):
        module = load_module()
        with self.assertRaisesRegex(ValueError, "no usable structured blocks"):
            module.RkVisionIRBuilder().normalize(
                {"pages": [{"page": 1, "blocks": []}]},
                document_name="empty.pdf",
            )


if __name__ == "__main__":
    unittest.main()
