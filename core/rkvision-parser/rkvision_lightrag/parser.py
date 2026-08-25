"""LightRAG parser adapter for the long-running RK3588 document-vision daemon.

The current native daemon emits an audited ``document.json`` and a lossless
reading-order ``document.md``.  This adapter persists the latter through the
official BaseParser contract; geometry and OCR provenance remain alongside it
in the daemon output directory for auditing.  A later sidecar writer can turn
those audited page blocks into the full LightRAG sidecar format without
changing the daemon protocol.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

from lightrag.parser.base import BaseParser, ParseContext, ParseResult


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
        output_dir = resolved.parsed_dir / "rkvision_raw"
        await _Daemon.request(source, output_dir)
        markdown_path = output_dir / "document.md"
        text = markdown_path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"rkvision extracted no usable text from {ctx.file_path}")
        await ctx.rag._persist_parsed_full_docs(ctx.doc_id, {
            "content": text,
            "file_path": ctx.file_path,
            "parse_format": "raw",
            "parse_engine": self.engine_name,
        })
        await ctx.archive_source(str(source))
        return ParseResult(
            doc_id=ctx.doc_id, file_path=ctx.file_path, parse_format="raw",
            content=text, blocks_path="", parse_engine=self.engine_name,
            parse_warnings={"rkvision_artifacts": str(output_dir)},
        )
