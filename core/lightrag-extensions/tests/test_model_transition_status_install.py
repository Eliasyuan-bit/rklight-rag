import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "model_transition_status_install",
    ROOT / "install_lightrag_model_transition_status_hook.py",
)
installer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(installer)


class ModelTransitionStatusInstallTest(unittest.TestCase):
    def test_pipeline_and_health_remain_busy_during_model_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            document_routes = Path(directory) / "document_routes.py"
            document_routes.write_text(
                "import os\n"
                "status_dict = pipeline_status.copy()\n"
                + installer.DOCUMENT_ANCHOR,
                encoding="utf-8",
            )
            server = Path(directory) / "server.py"
            server.write_text(
                "import os\n" + installer.HEALTH_ANCHOR,
                encoding="utf-8",
            )

            installer.install_document_routes(document_routes)
            installer.install_server(server)

            document_source = document_routes.read_text(encoding="utf-8")
            server_source = server.read_text(encoding="utf-8")
            self.assertIn('status_dict["busy"] = True', document_source)
            self.assertIn("or model_transition_active()", server_source)
            self.assertEqual(document_source.count(installer.MARKER), 1)
            self.assertEqual(server_source.count(installer.MARKER), 1)

            installer.install_document_routes(document_routes)
            installer.install_server(server)
            self.assertEqual(
                document_routes.read_text(encoding="utf-8").count(installer.MARKER), 1
            )


if __name__ == "__main__":
    unittest.main()
