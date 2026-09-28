import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "user_prompt_fallback_install",
    ROOT / "install_lightrag_user_prompt_fallback_hook.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class UserPromptFallbackInstallTest(unittest.TestCase):
    def test_empty_prompt_uses_environment_default(self):
        source = '''import os
async def _build_context_str():
    user_prompt = query_param.user_prompt if query_param.user_prompt else ""
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operate.py"
            path.write_text(source)
            MODULE.install(path)
            installed = path.read_text()
        self.assertIn(MODULE.MARKER, installed)
        self.assertIn('else os.getenv("RK_DEFAULT_USER_PROMPT", "")', installed)
        self.assertIn("query_param.user_prompt.strip()", installed)

    def test_install_is_idempotent(self):
        source = '''import os
async def _build_context_str():
    user_prompt = query_param.user_prompt if query_param.user_prompt else ""
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operate.py"
            path.write_text(source)
            MODULE.install(path)
            once = path.read_text()
            MODULE.install(path)
            self.assertEqual(path.read_text(), once)


if __name__ == "__main__":
    unittest.main()
