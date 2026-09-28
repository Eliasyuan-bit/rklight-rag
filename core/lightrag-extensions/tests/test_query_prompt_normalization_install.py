import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "query_prompt_normalization_install",
    ROOT / "install_lightrag_query_prompt_normalization_hook.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class QueryPromptNormalizationInstallTest(unittest.TestCase):
    def test_installs_blank_prompt_normalizer_before_query_validator(self):
        source = '''class QueryRequest:
    @field_validator("query", mode="after")
    @classmethod
    def query_strip_after(cls, query):
        return query
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "query_routes.py"
            path.write_text(source)
            MODULE.install(path)
            installed = path.read_text()
        self.assertIn(MODULE.MARKER, installed)
        self.assertIn('@field_validator("user_prompt", mode="before")', installed)
        self.assertIn('os.getenv("RK_DEFAULT_USER_PROMPT") or None', installed)


if __name__ == "__main__":
    unittest.main()
