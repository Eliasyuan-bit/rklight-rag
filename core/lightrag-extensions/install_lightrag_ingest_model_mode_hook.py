#!/usr/bin/env python3
"""Wrap LightRAG's central document-processing run in gateway ingest mode."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK_SINGLE_CARD_INGEST_MODEL_MODE_V3\n"
V2_MARKER = "# RK_SINGLE_CARD_INGEST_MODEL_MODE_V2\n"
OLD_MARKER = "# RK_SINGLE_CARD_INGEST_MODEL_MODE\n"
IMPORT_ANCHOR = "import uuid\n"
IMPORT_INSERT = '''import uuid

# RK_SINGLE_CARD_INGEST_MODEL_MODE_V3
from lightrag.rk_ingest_model_mode import (
    enter_ingest_model_mode,
    leave_ingest_model_mode,
)
'''
STATE_ANCHOR = '''        uncommitted_wakeup = False
        ingress = None
'''
STATE_INSERT = '''        uncommitted_wakeup = False
        ingress = None
        ingest_model_mode_active = False
'''
BEGIN_ANCHOR = '''            # Process documents until no more documents or requests
            while True:
'''
BEGIN_INSERT = '''            # Keep the reranker unloaded for the complete processing run,
            # not once per chunk. Query-mode workers are restored in finally.
            await enter_ingest_model_mode()
            ingest_model_mode_active = True

            # Process documents until no more documents or requests
            while True:
'''
END_ANCHOR = '''            await run_to_completion(_finalize)
'''
OLD_END_INSERT = '''            try:
                await run_to_completion(_finalize)
            finally:
                if ingest_model_mode_active:
                    await run_to_completion(leave_ingest_model_mode)
'''
END_INSERT = '''            model_restore_error = None
            if ingest_model_mode_active:
                restoring_message = (
                    "Document content processed; restoring query LLM, reranker, "
                    "and embedding models"
                )
                async with pipeline_status_lock:
                    pipeline_status["latest_message"] = restoring_message
                    append_pipeline_history(pipeline_status, restoring_message)
                try:
                    await run_to_completion(leave_ingest_model_mode)
                    ingest_model_mode_active = False
                    ready_message = (
                        "Query LLM, reranker, and embedding models are ready"
                    )
                    async with pipeline_status_lock:
                        pipeline_status["latest_message"] = ready_message
                        append_pipeline_history(pipeline_status, ready_message)
                    # Let the normal finalizer release the busy flag, but keep
                    # the final user-facing state explicit instead of the
                    # generic "pipeline stopped" message.
                    stopped_message = (
                        "Document indexing completed; query LLM, reranker, "
                        "and embedding models are ready"
                    )
                except BaseException as exc:
                    model_restore_error = exc

            await run_to_completion(_finalize)

            if model_restore_error is not None:
                restore_error_message = (
                    "Document content was processed, but query model restoration "
                    f"failed: {model_restore_error}"
                )
                async with pipeline_status_lock:
                    pipeline_status["latest_message"] = restore_error_message
                    append_pipeline_history(pipeline_status, restore_error_message)
                raise model_restore_error
'''
V2_END_INSERT = END_INSERT.replace(
    '''                    # Let the normal finalizer release the busy flag, but keep
                    # the final user-facing state explicit instead of the
                    # generic "pipeline stopped" message.
                    stopped_message = (
                        "Document indexing completed; query LLM, reranker, "
                        "and embedding models are ready"
                    )
''',
    "",
)


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(
            f"unsupported LightRAG pipeline source; expected one {label}, got {count}"
        )
    return source.replace(old, new, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    source = args.target.read_text(encoding="utf-8")
    if MARKER in source:
        return
    if V2_MARKER in source:
        source = replace_once(source, V2_MARKER, MARKER, "v2 marker")
        source = replace_once(
            source, V2_END_INSERT, END_INSERT, "v2 completion message"
        )
        args.target.write_text(source, encoding="utf-8")
        return
    if OLD_MARKER in source:
        source = replace_once(source, OLD_MARKER, MARKER, "v1 marker")
        source = replace_once(
            source, OLD_END_INSERT, END_INSERT, "v1 finalize ordering"
        )
        args.target.write_text(source, encoding="utf-8")
        return
    source = replace_once(source, IMPORT_ANCHOR, IMPORT_INSERT, "import anchor")
    source = replace_once(source, STATE_ANCHOR, STATE_INSERT, "state anchor")
    source = replace_once(source, BEGIN_ANCHOR, BEGIN_INSERT, "begin anchor")
    source = replace_once(source, END_ANCHOR, END_INSERT, "finalize anchor")
    args.target.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
