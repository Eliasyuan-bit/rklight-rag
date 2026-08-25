#!/usr/bin/env python3
"""Install the RK3588 single-active-query gate into LightRAG's query routes.

The gateway has one shared multi-card LLM.  Running more than one answer at a
time makes latency unpredictable and, more importantly, lets concurrent WebUI
streams look as though their answers belong to the wrong question.  This hook
adds a process-wide lease and a small read-only status endpoint.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path


MARKER = "# RK3588_SINGLE_ACTIVE_QUERY_GATE\n"
FIFO_MARKER = "# RK3588_QUERY_FIFO_GATE\n"
IMPORT_ANCHOR = "from fastapi import APIRouter, Depends\n"
IMPORT_INSERT = "from fastapi import APIRouter, Depends, HTTPException\nfrom datetime import datetime, timezone\nfrom uuid import uuid4\nimport os\n"
FACTORY_ANCHOR = "    combined_auth = get_combined_auth_dependency(api_key)\n"
FACTORY_INSERT = '''    combined_auth = get_combined_auth_dependency(api_key)

    # RK3588_QUERY_FIFO_GATE_V2
    # WORKERS=1: this coordinator deliberately governs every WebUI/API client
    # served by this LightRAG process, not merely one browser session.
    class QueryCoordinator:
        def __init__(self):
            self._condition = asyncio.Condition()
            self._active = None
            self._waiting = []
            self._max_waiting = max(1, int(os.getenv("RK_QUERY_MAX_QUEUE", "5")))

        async def acquire(self, question: str, mode: str):
            lease = {
                "request_id": f"query-{uuid4().hex[:12]}",
                "question": question,
                "mode": mode,
                "enqueued_at": datetime.now(timezone.utc).isoformat(),
            }
            async with self._condition:
                if len(self._waiting) >= self._max_waiting:
                    return None, self._snapshot_unlocked()
                self._waiting.append(lease)
                try:
                    while self._active is not None or self._waiting[0] is not lease:
                        await self._condition.wait()
                    self._waiting.pop(0)
                    lease["started_at"] = datetime.now(timezone.utc).isoformat()
                    self._active = lease
                    return dict(lease), None
                except BaseException:
                    if lease in self._waiting:
                        self._waiting.remove(lease)
                        self._condition.notify_all()
                    raise

        async def release(self, request_id: str):
            async with self._condition:
                if self._active is None or self._active["request_id"] != request_id:
                    return
                self._active = None
                self._condition.notify_all()

        def _snapshot_unlocked(self):
            # Public status intentionally contains no document/question text:
            # every WebUI user may see it, whereas query content is private.
            return {
                "busy": self._active is not None,
                "queue_length": len(self._waiting),
                "max_queue_length": self._max_waiting,
            }

        async def snapshot(self):
            async with self._condition:
                return self._snapshot_unlocked()

    query_coordinator = QueryCoordinator()

    async def release_after_stream(generator, lease):
        try:
            async for line in generator:
                yield line
        finally:
            await query_coordinator.release(lease["request_id"])

    @router.get("/query/status", dependencies=[Depends(combined_auth)])
    async def query_status():
        """Return the one globally active question without exposing client identity."""
        return await query_coordinator.snapshot()
'''

NONSTREAM_TRY = '''        try:
            param = request.to_query_params(
'''
NONSTREAM_TRY_INSERT = '''        lease = None
        try:
            lease, queue_full = await query_coordinator.acquire(request.query, request.mode)
            if queue_full:
                raise HTTPException(status_code=429, detail={"code": "query_queue_full", "status": queue_full})
            param = request.to_query_params(
'''
NONSTREAM_EXCEPT = '''        except Exception as e:
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            raise internal_server_error(e)

    def _build_stream_generator(
'''
NONSTREAM_EXCEPT_INSERT = '''        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            raise internal_server_error(e)
        finally:
            if lease:
                await query_coordinator.release(lease["request_id"])

    def _build_stream_generator(
'''

STREAM_TRY = '''        try:
            # Use the stream parameter from the request, defaulting to True if not specified
'''
STREAM_TRY_INSERT = '''        lease = None
        stream_handoff = False
        try:
            lease, queue_full = await query_coordinator.acquire(request.query, request.mode)
            if queue_full:
                raise HTTPException(status_code=429, detail={"code": "query_queue_full", "status": queue_full})
            # Use the stream parameter from the request, defaulting to True if not specified
'''
STREAM_MERGED = '''                return StreamingResponse(
                    merged_generator(),
'''
STREAM_MERGED_INSERT = '''                stream_handoff = True
                return StreamingResponse(
                    release_after_stream(merged_generator(), lease),
'''
STREAM_DEFAULT = '''                return StreamingResponse(
                    stream_gen(),
'''
STREAM_DEFAULT_INSERT = '''                stream_handoff = True
                return StreamingResponse(
                    release_after_stream(stream_gen(), lease),
'''
STREAM_EXCEPT = '''        except Exception as e:
            logger.error(f"Error processing streaming query: {str(e)}", exc_info=True)
            raise internal_server_error(e)

    @router.post(
        "/query/data",
'''
STREAM_EXCEPT_INSERT = '''        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error processing streaming query: {str(e)}", exc_info=True)
            raise internal_server_error(e)
        finally:
            if lease and not stream_handoff:
                await query_coordinator.release(lease["request_id"])

    @router.post(
        "/query/data",
'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise SystemExit(f"unsupported LightRAG source; missing {label}")
    return source.replace(old, new, 1)


def install(path: Path) -> None:
    source = path.read_text()
    if MARKER in source or "# RK3588_QUERY_FIFO_GATE" in source:
        upgrade_existing(path, source)
        return
    backup = path.with_suffix(path.suffix + ".before-rk3588-query-gate")
    if not backup.exists():
        backup.write_text(source)
    source = replace_once(source, IMPORT_ANCHOR, IMPORT_INSERT, "FastAPI import")
    source = replace_once(source, FACTORY_ANCHOR, FACTORY_INSERT, "router factory")
    source = replace_once(source, NONSTREAM_TRY, NONSTREAM_TRY_INSERT, "non-stream query")
    source = replace_once(source, NONSTREAM_EXCEPT, NONSTREAM_EXCEPT_INSERT, "non-stream cleanup")
    source = replace_once(source, STREAM_TRY, STREAM_TRY_INSERT, "stream query")
    source = replace_once(source, STREAM_MERGED, STREAM_MERGED_INSERT, "progress stream response")
    source = replace_once(source, STREAM_DEFAULT, STREAM_DEFAULT_INSERT, "default stream response")
    source = replace_once(source, STREAM_EXCEPT, STREAM_EXCEPT_INSERT, "stream cleanup")
    path.write_text(source)
    print(f"installed: {path}")


def upgrade_existing(path: Path, source: str) -> None:
    """Upgrade an already-installed gate without requiring a package reinstall."""
    if "# RK3588_QUERY_FIFO_GATE_V2" in source or "# RK3588_QUERY_FIFO_GATE_V3" in source:
        print(f"already installed: {path}")
        return
    if "# RK3588_QUERY_FIFO_GATE" in source:
        source = source.replace("# RK3588_QUERY_FIFO_GATE", "# RK3588_QUERY_FIFO_GATE_V2", 1)
        public_snapshot = '''        def _snapshot_unlocked(self):
            # Public status intentionally contains no document/question text:
            # every WebUI user may see it, whereas query content is private.
            return {
                "busy": self._active is not None,
                "queue_length": len(self._waiting),
                "max_queue_length": self._max_waiting,
            }

'''
        source, count = re.subn(
            r"        def _snapshot_unlocked\(self\):\n.*?(?=        async def snapshot\(self\):)",
            public_snapshot,
            source,
            count=1,
            flags=re.S,
        )
        if count != 1:
            raise SystemExit("unable to redact FIFO query status")
        path.write_text(source)
        print(f"upgraded FIFO status privacy: {path}")
        return
    if "# RK3588_SINGLE_ACTIVE_QUERY_GATE" not in source:
        raise SystemExit("unknown RK3588 query-gate variant")
    if "import os\n" not in source:
        source = source.replace("from uuid import uuid4\n", "from uuid import uuid4\nimport os\n", 1)
    queue_class = FACTORY_INSERT.split("    query_coordinator = QueryCoordinator()\n", 1)[0]
    source, count = re.subn(
        r"    # RK3588_SINGLE_ACTIVE_QUERY_GATE\n.*?(?=    query_coordinator = QueryCoordinator\(\)\n)",
        queue_class,
        source,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise SystemExit("unable to replace old query coordinator")
    source = source.replace(
        'lease, busy = await query_coordinator.acquire(request.query, request.mode)\n            if busy:\n                raise HTTPException(status_code=409, detail={"code": "query_busy", "active": busy})',
        'lease, queue_full = await query_coordinator.acquire(request.query, request.mode)\n            if queue_full:\n                raise HTTPException(status_code=429, detail={"code": "query_queue_full", "status": queue_full})',
    )
    if "lease, busy = await query_coordinator.acquire" in source:
        raise SystemExit("unable to upgrade query acquire calls")
    path.write_text(source)
    print(f"upgraded to FIFO queue: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("query_routes", type=Path)
    install(parser.parse_args().query_routes)
