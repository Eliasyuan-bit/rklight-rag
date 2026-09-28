from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "pdf_table_parse.py"


def load_module():
    spec = importlib.util.spec_from_file_location("pdf_table_parse_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class NativeGlyphFillTests(unittest.TestCase):
    def test_native_glyphs_replace_ocr_and_preserve_spaces(self):
        module = load_module()
        cells = [
            {
                "row": 0,
                "col": 0,
                "row_span": 1,
                "col_span": 1,
                "label": "ched",
                "page_box": [0.0, 0.0, 100.0, 30.0],
                "text": "TTFT (sm)",
            },
            {
                "row": 0,
                "col": 1,
                "row_span": 1,
                "col_span": 1,
                "label": "ched",
                "page_box": [100.0, 0.0, 220.0, 30.0],
                "text": "ModelName",
            },
        ]
        glyphs = []
        x = 4.0
        for index, character in enumerate("TTFT (ms)"):
            if character == " ":
                continue
            glyphs.append(
                {
                    "text": character,
                    "space_before": index == 5,
                    "box": [x, 5.0, x + 5.0, 15.0],
                }
            )
            x += 7.0
        x = 110.0
        for index, character in enumerate("Model Name"):
            if character == " ":
                continue
            glyphs.append(
                {
                    "text": character,
                    "space_before": index == 6,
                    "box": [x, 5.0, x + 5.0, 15.0],
                }
            )
            x += 7.0

        replaced = module.fill_cells_from_native_glyphs(cells, glyphs)

        self.assertEqual(replaced, 2)
        self.assertEqual(cells[0]["text"], "TTFT (ms)")
        self.assertEqual(cells[1]["text"], "Model Name")
        self.assertEqual(cells[0]["text_source"], "pdfium")
        self.assertEqual(cells[0]["ocr_text"], "TTFT (sm)")
        self.assertIn("| TTFT (ms) | Model Name |", module.cells_to_markdown(cells))

    def test_missing_native_glyphs_keep_ocr_fallback(self):
        module = load_module()
        cells = [
            {
                "row": 0,
                "col": 0,
                "row_span": 1,
                "col_span": 1,
                "label": "fcel",
                "page_box": [0.0, 0.0, 50.0, 20.0],
                "text": "OCR only",
            }
        ]

        replaced = module.fill_cells_from_native_glyphs(cells, [])

        self.assertEqual(replaced, 0)
        self.assertEqual(cells[0]["text"], "OCR only")

    def test_visual_line_break_after_hyphen_does_not_add_space(self):
        module = load_module()
        cells = [
            {
                "row": 0,
                "col": 0,
                "row_span": 1,
                "col_span": 1,
                "label": "fcel",
                "page_box": [0.0, 0.0, 100.0, 50.0],
                "text": "2025-08- 16",
            }
        ]
        glyphs = []
        for index, character in enumerate("2025-08-"):
            glyphs.append(
                {
                    "text": character,
                    "space_before": False,
                    "box": [index * 6.0, 2.0, index * 6.0 + 5.0, 12.0],
                }
            )
        for index, character in enumerate("16"):
            glyphs.append(
                {
                    "text": character,
                    "space_before": False,
                    "box": [index * 6.0, 25.0, index * 6.0 + 5.0, 35.0],
                }
            )

        module.fill_cells_from_native_glyphs(cells, glyphs)

        self.assertEqual(cells[0]["text"], "2025-08-16")


if __name__ == "__main__":
    unittest.main()
