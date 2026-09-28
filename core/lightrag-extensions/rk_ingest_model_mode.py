"""Switch the board-local model gateway around a complete ingestion run."""
from __future__ import annotations

import asyncio
import json
import os
import threading
from urllib.request import Request, urlopen


_transition_lock = threading.Lock()
_transition_active = False


def _set_model_transition_active(active: bool) -> None:
    global _transition_active
    with _transition_lock:
        _transition_active = active


def model_transition_active() -> bool:
    """Return whether ingestion owns or is restoring the single-card models."""
    with _transition_lock:
        return _transition_active


def _enabled() -> bool:
    return os.getenv("RK_INGEST_MODEL_MODE_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _switch(path: str) -> dict:
    base = os.getenv(
        "RK_MODEL_GATEWAY_ADMIN_URL", "http://127.0.0.1:8100"
    ).rstrip("/")
    timeout = float(os.getenv("RK_MODEL_GATEWAY_ADMIN_TIMEOUT", "240"))
    request = Request(
        base + path,
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"model gateway mode switch failed: {payload}")
    return payload


async def enter_ingest_model_mode() -> dict | None:
    if not _enabled():
        return None
    _set_model_transition_active(True)
    try:
        return await asyncio.to_thread(_switch, "/admin/ingest/begin")
    except BaseException:
        _set_model_transition_active(False)
        raise


async def leave_ingest_model_mode() -> dict | None:
    if not _enabled():
        return None
    result = await asyncio.to_thread(_switch, "/admin/ingest/end")
    # The gateway endpoint returns only after 2B, reranker and embedding have
    # all completed their startup health checks.
    _set_model_transition_active(False)
    return result
