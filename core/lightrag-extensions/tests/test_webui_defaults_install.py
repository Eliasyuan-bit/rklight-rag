from pathlib import Path
import sys
import tempfile
import unittest


EXTENSIONS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXTENSIONS))
from install_lightrag_webui_defaults import install  # noqa: E402


class WebUiDefaultsInstallTest(unittest.TestCase):
    def test_installs_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "src/stores/settings.ts"
            query = root / "src/components/retrieval/QuerySettings.tsx"
            settings.parent.mkdir(parents=True)
            query.parent.mkdir(parents=True)
            settings.write_text(
                """      querySettings: {
        top_k: 40,
        chunk_top_k: 20,
        max_entity_tokens: 6000,
        max_relation_tokens: 8000,
        max_total_tokens: 30000,
      },
      version: 21,
      migrate: () => {
        return state
      }
    }
  )
)""",
                encoding="utf-8",
            )
            query.write_text(
                """  const defaultValues = {
    top_k: 40,
    chunk_top_k: 20,
    max_entity_tokens: 6000,
    max_relation_tokens: 8000,
    max_total_tokens: 30000
  }""",
                encoding="utf-8",
            )

            install(root)
            installed = settings.read_text(encoding="utf-8")
            self.assertIn("      version: 23,", installed)
            self.assertIn("if (version < 22)", installed)
            self.assertIn("max_total_tokens: 3600", query.read_text(encoding="utf-8"))

            install(root)
            self.assertEqual(installed, settings.read_text(encoding="utf-8"))

    def test_rejects_unknown_upstream_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "src/stores/settings.ts"
            query = root / "src/components/retrieval/QuerySettings.tsx"
            settings.parent.mkdir(parents=True)
            query.parent.mkdir(parents=True)
            settings.write_text("unknown", encoding="utf-8")
            query.write_text("unknown", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                install(root)


if __name__ == "__main__":
    unittest.main()
