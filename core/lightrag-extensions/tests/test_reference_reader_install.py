import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "install_reference_reader_test", ROOT / "install_lightrag_reference_reader.py"
)
installer = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(installer)


class ReferenceReaderInstallTest(unittest.TestCase):
    def test_inserts_script_once_and_updates_asset(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            index = directory / "index.html"
            index.write_text("<html>\n  </body>\n</html>")
            script = ROOT / "webui" / "reference-reader.js"
            installer.install(directory, script)
            installer.install(directory, script)
            self.assertEqual(index.read_text().count(installer.MARKER), 1)
            self.assertEqual((directory / "reference-reader.js").read_text(), script.read_text())


if __name__ == "__main__":
    unittest.main()
