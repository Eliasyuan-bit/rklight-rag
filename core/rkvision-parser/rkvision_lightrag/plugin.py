"""Cheap entry-point registration; parser implementation stays lazy-loaded."""
from __future__ import annotations

import os

from lightrag.parser.registry import ParserSpec, register_parser


def register() -> None:
    register_parser(
        ParserSpec(
            engine_name="rkvision",
            impl="rkvision_lightrag.parser:RkVisionParser",
            suffixes=frozenset({"pdf"}),
            queue_group="rkvision",
            concurrency=int(os.getenv("MAX_PARALLEL_PARSE_RKVISION", "1")),
            endpoint_configured=lambda: bool(os.getenv("RK_VISION_DAEMON", "").strip()),
            endpoint_requirement=lambda: "RK_VISION_DAEMON",
        )
    )
