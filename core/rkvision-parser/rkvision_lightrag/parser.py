"""Structured LightRAG adapter for the RK3588 document-vision daemon.

The native daemon emits audited page blocks in ``document.json``.  This
adapter maps their headings, tables, page anchors and bounding boxes into the
official LightRAG sidecar IR, writes ``blocks.jsonl`` and persists the raw
RKVision result beside it for troubleshooting.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from lightrag.constants import FULL_DOCS_FORMAT_LIGHTRAG
from lightrag.parser.base import BaseParser, ParseContext, ParseResult

from .ir_builder import RkVisionIRBuilder


class _Daemon:
    process: subprocess.Popen[str] | None = None
    lock: asyncio.Lock | None = None

    @classmethod
    async def request(cls, source: Path, output_dir: Path) -> dict:
        if cls.lock is None:
            cls.lock = asyncio.Lock()
        async with cls.lock:
            if cls.process is None or cls.process.poll() is not None:
                command = os.environ["RK_VISION_DAEMON"]
                cls.process = subprocess.Popen(
                    [command, "--layout-model", os.environ["RK_VISION_LAYOUT_MODEL"],
                     "--ocr-models", os.environ["RK_VISION_OCR_MODELS"], "--dict",
                     os.environ["RK_VISION_OCR_DICT"]],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, bufsize=1,
                )
                ready = await asyncio.to_thread(cls.process.stdout.readline)
                if json.loads(ready).get("ready") is not True:
                    raise RuntimeError(f"document-vision daemon did not become ready: {ready.strip()}")
            assert cls.process.stdin is not None and cls.process.stdout is not None
            request_id = f"rkvision-{uuid4().hex}"
            cls.process.stdin.write(json.dumps({"id": request_id, "input": str(source), "output_dir": str(output_dir)}) + "\n")
            cls.process.stdin.flush()
            reply = json.loads(await asyncio.to_thread(cls.process.stdout.readline))
            if reply.get("id") != request_id or not reply.get("ok"):
                raise RuntimeError(reply.get("error", "document-vision daemon failed"))
            return reply


class RkVisionParser(BaseParser):
    engine_name = "rkvision"

    async def parse(self, ctx: ParseContext) -> ParseResult:
        resolved = ctx.resolve(self.engine_name)
        source = resolved.source_path
        if not source.is_file():
            raise FileNotFoundError(f"rkvision source not found: {source}")
        output_dir = resolved.parsed_dir / ".rkvision_raw"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        await _Daemon.request(source, output_dir)
        document_path = output_dir / "document.json"
        if not document_path.is_file():
            raise ValueError(f"rkvision did not produce document.json for {ctx.file_path}")

        tableformer_summary = await _restore_tables(source, output_dir, document_path)

        from lightrag.sidecar import write_sidecar
        from lightrag.utils_pipeline import make_lightrag_doc_content, sidecar_uri_for

        ir = RkVisionIRBuilder().normalize_from_path(
            document_path, document_name=resolved.document_name
        )
        _clear_previous_sidecar(resolved.parsed_dir, resolved.document_name)
        parsed_data = write_sidecar(
            ir,
            parsed_dir=resolved.parsed_dir,
            doc_id=ctx.doc_id,
            engine=self.engine_name,
            clean_parsed_dir=False,
        )
        await ctx.rag._persist_parsed_full_docs(ctx.doc_id, {
            "content": make_lightrag_doc_content(parsed_data["content"]),
            "file_path": ctx.file_path,
            "parse_format": FULL_DOCS_FORMAT_LIGHTRAG,
            "sidecar_location": sidecar_uri_for(resolved.parsed_dir),
            "parse_engine": self.engine_name,
            "update_time": int(time.time()),
        })
        await ctx.archive_source(str(source))
        return ParseResult(
            doc_id=ctx.doc_id,
            file_path=ctx.file_path,
            parse_format=FULL_DOCS_FORMAT_LIGHTRAG,
            content=parsed_data["content"],
            blocks_path=parsed_data["blocks_path"],
            parse_engine=self.engine_name,
            parse_warnings={
                "rkvision_artifacts": str(output_dir),
                **({"tableformer": tableformer_summary} if tableformer_summary else {}),
            },
        )


async def _restore_tables(source: Path, output_dir: Path, document_path: Path) -> dict:
    """Optionally enrich RKVision output with TableFormer structure."""
    executable = os.environ.get("RK_VISION_TABLEFORMER_PDF", "").strip()
    if not executable:
        return {}
    command = [
        executable,
        str(source),
        str(output_dir),
        "--document-json",
        str(document_path),
    ]
    process_env = os.environ.copy()
    process_env.setdefault(
        "TF_DOCUMENT_VISION_ROOT", str(Path(os.environ["RK_VISION_DAEMON"]).parent.parent)
    )
    result = await asyncio.to_thread(
        subprocess.run,
        command,
        env=process_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "TableFormer PDF enrichment failed: "
            + (result.stderr.strip() or result.stdout.strip())
        )
    for line in reversed(result.stdout.splitlines()):
        try:
            summary = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(summary, dict):
            return summary
    raise RuntimeError("TableFormer PDF enrichment returned no JSON summary")


def _clear_previous_sidecar(parsed_dir: Path, document_name: str) -> None:
    """Remove only writer-owned outputs while preserving RKVision raw data."""
    base = Path(document_name).stem or document_name
    for suffix in (
        ".blocks.jsonl",
        ".tables.json",
        ".drawings.json",
        ".equations.json",
    ):
        target = parsed_dir / f"{base}{suffix}"
        if target.is_file():
            target.unlink()
    assets = parsed_dir / f"{base}.blocks.assets"
    if assets.is_dir():
        shutil.rmtree(assets)
