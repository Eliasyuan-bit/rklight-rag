import importlib.util
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "source_policy_install", ROOT / "install_lightrag_source_policy_hook.py"
)
installer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(installer)


class SourcePolicyInstallTest(unittest.TestCase):
    def test_installs_evidence_refiner_after_source_policy(self):
        source = (
            installer.IMPORT_ANCHOR
            + "\nasync def process():\n"
            + "        rerank_top_k = query_param.chunk_top_k or len(unique_chunks)\n"
            + "        unique_chunks = await apply_rerank_if_enabled(\n"
            + "            query=query,\n"
            + "            retrieved_docs=unique_chunks,\n"
            + "            global_config=global_config,\n"
            + "            enable_rerank=query_param.enable_rerank,\n"
            + "            top_n=rerank_top_k,\n"
            + "        )\n"
            + installer.RERANK_TRACE_ANCHOR
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "utils.py"
            target.write_text(source, encoding="utf-8")
            installer.install(target)
            installed = target.read_text(encoding="utf-8")

        self.assertIn("from lightrag.rk_evidence_refiner import", installed)
        self.assertIn("query_aware_rerank_top_n", installed)
        self.assertIn("fuse_query_aware_rerank", installed)
        self.assertIn("top_n=rerank_candidate_k", installed)
        self.assertLess(
            installed.index("apply_source_authority_policy"),
            installed.index("await refine_evidence_units"),
        )
        self.assertEqual(installed.count(installer.MARKER), 1)

    def test_upgrades_v2_installation(self):
        source = (
            "from lightrag.rk_source_policy import apply_source_authority_policy\n"
            "async def process():\n"
            "        rerank_top_k = query_param.chunk_top_k or len(unique_chunks)\n"
            "        unique_chunks = await apply_rerank_if_enabled(\n"
            "            query=query,\n"
            "            retrieved_docs=unique_chunks,\n"
            "            global_config=global_config,\n"
            "            enable_rerank=query_param.enable_rerank,\n"
            "            top_n=rerank_top_k,\n"
            "        )\n"
            "        unique_chunks = apply_source_authority_policy(unique_chunks, query)\n"
            f"        {installer.V2_MARKER}\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "utils.py"
            target.write_text(source, encoding="utf-8")
            installer.install(target)
            installed = target.read_text(encoding="utf-8")

        self.assertIn("await refine_evidence_units", installed)
        self.assertIn("query_aware_rerank_top_n", installed)
        self.assertIn(installer.MARKER, installed)
        self.assertNotIn(installer.V2_MARKER, installed)


if __name__ == "__main__":
    unittest.main()
