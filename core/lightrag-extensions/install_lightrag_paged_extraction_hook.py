#!/usr/bin/env python3
"""Install bounded stateless entity-extraction pagination into LightRAG."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_PAGED_EXTRACTION_V3"
OLD_MARKERS = ("# RK3588_PAGED_EXTRACTION_V1", "# RK3588_PAGED_EXTRACTION_V2")
IMPORT_ANCHOR = "from lightrag.prompt import PROMPTS, resolve_entity_extraction_prompt_profile\n"
IMPORT_INSERT = IMPORT_ANCHOR + '''from lightrag.rk_paged_extraction import (
    build_continue_prompt,
    build_seen_summary,
    extraction_needs_next_page,
    merge_extraction_page,
    split_extraction_windows,
)
# RK3588_PAGED_EXTRACTION_V3
'''

BLOCK_START = '''        history = pack_user_ass_to_openai_messages(
            entity_extraction_user_prompt, final_result
        )
'''
BLOCK_END = "        # Inject multimodal entity + associations for drawing/table/equation\n"
INSTALLED_BLOCK_START = "        # Parse the first bounded page, then continue with fresh prompts that\n"
CONTENT_ANCHOR = '''        content = strip_internal_multimodal_markup_for_extraction(chunk_dp["content"])
'''
CONTENT_REPLACEMENT = '''        content = strip_internal_multimodal_markup_for_extraction(chunk_dp["content"])
        extraction_windows = split_extraction_windows(
            content,
            max_chars=max(80, get_env_value("EXTRACTION_PAGE_CHARS", 220, int)),
        )
        # The first request is built below from the first extraction-only
        # window. Stored chunk content and citations remain unchanged.
        content = extraction_windows[0]
'''
TALLY_ANCHOR = "    stage_tally = TokenLimitTruncationTally()\n"
TALLY_REPLACEMENT = TALLY_ANCHOR + '''    recovered_truncation_chunks: set[str] = set()
    unresolved_truncation_chunks: set[str] = set()
    unresolved_truncation_tally = TokenLimitTruncationTally()
'''
REPORT_ANCHOR = '''        cache_keys_collector = []

        def _report_truncation(result: str, stage: str) -> None:
            if not is_truncated_response(result):
                return
'''
REPORT_REPLACEMENT = '''        cache_keys_collector = []
        chunk_had_token_truncation = False

        def _report_truncation(result: str, stage: str) -> None:
            nonlocal chunk_had_token_truncation
            if not is_truncated_response(result):
                return
            chunk_had_token_truncation = True
'''
SUMMARY_ANCHOR = '''        if not stage_tally:
            return
        truncation_message = (
            f"Warning: token-limit truncation hit {stage_tally.affected} of "
            f"{total_chunks} chunks during entity extraction "
            f"({stage_tally.stage_breakdown()}); "
            f"extracted knowledge may be incomplete"
        )
        logger.warning(truncation_message)
        status_logger.log(truncation_message)
        if truncation_tally is not None:
            truncation_tally.absorb(stage_tally)
'''
SUMMARY_REPLACEMENT = '''        if not stage_tally:
            return
        if (
            stage_tally.affected == len(recovered_truncation_chunks)
            and not unresolved_truncation_chunks
        ):
            recovery_message = (
                f"Token-limit truncation recovered for all "
                f"{stage_tally.affected} affected chunks during entity extraction "
                f"({stage_tally.stage_breakdown()})"
            )
            logger.info(recovery_message)
            status_logger.log(recovery_message)
            return
        truncation_message = (
            f"Warning: unresolved token-limit truncation affected "
            f"{len(unresolved_truncation_chunks)} of {total_chunks} chunks "
            f"during entity extraction ({stage_tally.stage_breakdown()}); "
            f"extracted knowledge may be incomplete"
        )
        logger.warning(truncation_message)
        status_logger.log(truncation_message)
        if truncation_tally is not None:
            truncation_tally.absorb(unresolved_truncation_tally)
'''
BLOCK_REPLACEMENT = '''        # Parse the first bounded page, then continue with fresh prompts that
        # carry only compact record identities. Never replay the prior generated
        # descriptions: doing so wastes the 4K context window and can make page 2
        # fail before it starts generating.
        if use_json_extraction:
            maybe_nodes, maybe_edges = await _process_json_extraction_result(
                final_result,
                chunk_key,
                timestamp,
                file_path,
            )
        else:
            maybe_nodes, maybe_edges = await _process_extraction_result(
                final_result,
                chunk_key,
                timestamp,
                file_path,
                tuple_delimiter=context_base["tuple_delimiter"],
                completion_delimiter=context_base["completion_delimiter"],
            )

        max_pages_per_window = max(
            1, get_env_value("MAX_EXTRACTION_PAGES_PER_WINDOW", 2, int)
        )
        max_extraction_pages = max(
            len(extraction_windows) * max_pages_per_window,
            get_env_value("MAX_EXTRACTION_PAGES", 6, int),
        )
        page_no = 1
        window_index = 0
        window_page_no = 1
        no_progress_pages = 0
        had_unresolved_window = False
        current_result = final_result
        pagination_started = (
            len(extraction_windows) > 1
            or extraction_needs_next_page(
                current_result, truncated=is_truncated_response(current_result)
            )
        )

        # JSON response mode has no safe partial-object salvage contract. Keep
        # its upstream one-shot behavior until a JSON pagination schema exists.
        while not use_json_extraction and page_no < max_extraction_pages:
            current_window_unfinished = extraction_needs_next_page(
                current_result, truncated=is_truncated_response(current_result)
            )
            window_limit_reached = window_page_no >= max_pages_per_window
            if not current_window_unfinished or window_limit_reached:
                if (
                    current_window_unfinished
                    and window_limit_reached
                    and is_truncated_response(current_result)
                ):
                    had_unresolved_window = True
                    logger.warning(
                        f"Extraction window {window_index + 1} unresolved for "
                        f"chunk {chunk_key}: token-limit truncation persisted "
                        f"after {max_pages_per_window} pages"
                    )
                if window_index + 1 >= len(extraction_windows):
                    break
                window_index += 1
                window_page_no = 0
                no_progress_pages = 0

            page_no += 1
            window_page_no += 1
            continue_prompt = build_continue_prompt(
                input_text=extraction_windows[window_index],
                heading_context_block=heading_context_block,
                seen_summary=build_seen_summary(maybe_nodes, maybe_edges),
                page_no=page_no,
                max_pages=max_extraction_pages,
                window_no=window_index + 1,
                window_count=len(extraction_windows),
                max_total_records=max_total_records,
                max_entity_records=max_entity_records,
                language=language,
            )
            page_result, page_timestamp = await use_llm_func_with_cache(
                continue_prompt,
                use_llm_func,
                system_prompt=entity_extraction_system_prompt,
                llm_response_cache=llm_response_cache,
                cache_type="extract",
                chunk_id=chunk_key,
                cache_keys_collector=cache_keys_collector,
                llm_cache_identity=get_llm_cache_identity(global_config, "extract"),
            )
            _report_truncation(page_result, f"page-{page_no}")
            page_nodes, page_edges = await _process_extraction_result(
                page_result,
                chunk_key,
                page_timestamp,
                file_path,
                tuple_delimiter=context_base["tuple_delimiter"],
                completion_delimiter=context_base["completion_delimiter"],
            )
            added = merge_extraction_page(
                maybe_nodes, maybe_edges, page_nodes, page_edges
            )
            current_result = page_result
            page_truncated = is_truncated_response(page_result)
            if added == 0 and current_window_unfinished and not page_truncated:
                # Small local models sometimes omit both terminal markers even
                # when generation stopped normally. One stateless audit page
                # with no new keys is positive evidence that this extraction
                # window is exhausted; advance instead of falsely reporting an
                # unresolved token-limit truncation.
                current_result = context_base["completion_delimiter"]
                no_progress_pages = 0
            elif added == 0 and current_window_unfinished:
                no_progress_pages += 1
                if no_progress_pages >= 2:
                    had_unresolved_window = True
                    logger.warning(
                        f"Extraction window {window_index + 1} unresolved for "
                        f"chunk {chunk_key}: two continuation pages produced "
                        "no new records"
                    )
                    if window_index + 1 >= len(extraction_windows):
                        break
                    window_index += 1
                    window_page_no = 0
                    no_progress_pages = 0
                    current_result = "<|MORE|>"
            else:
                no_progress_pages = 0

        pagination_unresolved = had_unresolved_window or (
            not use_json_extraction
            and is_truncated_response(current_result)
        )
        if pagination_unresolved:
            if chunk_had_token_truncation:
                unresolved_truncation_chunks.add(chunk_key)
                unresolved_truncation_tally.record("entity-extraction", chunk_key)
            message = (
                f"Paged extraction unresolved for chunk {chunk_key} after "
                f"{page_no}/{max_extraction_pages} pages"
            )
            logger.warning(message)
            status_logger.log(f"Warning: {message}")
        elif pagination_started:
            if chunk_had_token_truncation:
                recovered_truncation_chunks.add(chunk_key)
            logger.info(
                f"Paged extraction recovered chunk {chunk_key} in {page_no} pages"
            )

'''

PROMPT_REPLACEMENTS = (
    (
        "`entity_description`: Provide a concise yet comprehensive description of the entity's attributes and activities, based *solely* on the information present in the input text.",
        "`entity_description`: Provide one compact factual phrase of at most 16 words, based *solely* on the input text. Do not list secondary attributes.",
    ),
    (
        "`relationship_description`: A concise explanation of the nature of the relationship between the source and target entities.",
        "`relationship_description`: One compact factual phrase of at most 20 words describing the direct relationship.",
    ),
    (
        "Only output relationship rows whose source and target entities are both included in the selected entity rows for this response.",
        "Only output relationship rows whose source and target entities are included in this response or listed under `---Already Extracted---`.",
    ),
    (
        "If the limit is reached, stop adding new rows immediately and output `{completion_delimiter}`.",
        "If the limit is reached while relevant records remain, stop adding rows and output `<|MORE|>`. Output `{completion_delimiter}` only after the input is fully exhausted.",
    ),
    (
        "9. **Completion Signal:** Output the literal string `{completion_delimiter}` only after all entities and relationships have been completely extracted and outputted.",
        "9. **Pagination Signal:** Output `<|MORE|>` when relevant unreported records remain. Output the literal string `{completion_delimiter}` only after all entities and relationships have been completely extracted.",
    ),
    (
        "4. **Completion Signal:** Output `{completion_delimiter}` as the final line after all relevant entities and relationships have been extracted and presented. If the row limit is reached, output `{completion_delimiter}` immediately after the last allowed row.",
        "4. **Pagination Signal:** If relevant unreported records remain or the row limit is reached, output `<|MORE|>` after the last row. Output `{completion_delimiter}` only when the input is fully exhausted.",
    ),
    (
        "5. **Completion Signal:** Output `{completion_delimiter}` as the final line after all relevant missing or corrected entities and relationships have been extracted and presented. If the row limit is reached, output `{completion_delimiter}` immediately after the last allowed row.",
        "5. **Pagination Signal:** If relevant unreported records remain or the row limit is reached, output `<|MORE|>` after the last row. Output `{completion_delimiter}` only when the input is fully exhausted.",
    ),
)


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise SystemExit(
            f"unsupported LightRAG source; expected one {label}, got {source.count(old)}"
        )
    return source.replace(old, new, 1)


def replace_block(source: str) -> str:
    start = source.find(BLOCK_START)
    if start < 0:
        raise SystemExit("unsupported LightRAG source; pagination start anchor missing")
    end = source.find(BLOCK_END, start)
    if end < 0:
        raise SystemExit("unsupported LightRAG source; pagination end anchor missing")
    if source.find(BLOCK_START, start + 1) >= 0:
        raise SystemExit("unsupported LightRAG source; pagination start anchor is ambiguous")
    return source[:start] + BLOCK_REPLACEMENT + source[end:]


def upgrade_installed_block(source: str) -> str:
    start = source.find(INSTALLED_BLOCK_START)
    end = source.find(BLOCK_END, start)
    if start < 0 or end < 0 or source.find(INSTALLED_BLOCK_START, start + 1) >= 0:
        raise SystemExit("unsupported installed LightRAG pagination block")
    upgraded = source[:start] + BLOCK_REPLACEMENT + source[end:]
    for old_marker in OLD_MARKERS:
        if old_marker in upgraded:
            upgraded = upgraded.replace(old_marker, MARKER, 1)
            break
    return upgraded


def install(operate_path: Path, prompt_path: Path) -> None:
    operate_source = operate_path.read_text(encoding="utf-8")
    prompt_source = prompt_path.read_text(encoding="utf-8")
    if MARKER in operate_source:
        print(f"already installed: {operate_path}")
        return
    if any(old_marker in operate_source for old_marker in OLD_MARKERS):
        operate_path.write_text(
            upgrade_installed_block(operate_source), encoding="utf-8"
        )
        print(f"upgraded: {operate_path}")
        return

    operate_backup = operate_path.with_suffix(
        operate_path.suffix + ".before-rk3588-paged-extraction"
    )
    prompt_backup = prompt_path.with_suffix(
        prompt_path.suffix + ".before-rk3588-paged-extraction"
    )
    if not operate_backup.exists():
        operate_backup.write_text(operate_source, encoding="utf-8")
    if not prompt_backup.exists():
        prompt_backup.write_text(prompt_source, encoding="utf-8")

    operate_source = replace_once(
        operate_source, IMPORT_ANCHOR, IMPORT_INSERT, "prompt import"
    )
    operate_source = replace_once(
        operate_source, TALLY_ANCHOR, TALLY_REPLACEMENT, "truncation tally"
    )
    operate_source = replace_once(
        operate_source, REPORT_ANCHOR, REPORT_REPLACEMENT, "truncation reporter"
    )
    operate_source = replace_once(
        operate_source,
        CONTENT_ANCHOR,
        CONTENT_REPLACEMENT,
        "extraction content",
    )
    operate_source = replace_block(operate_source)
    operate_source = replace_once(
        operate_source,
        SUMMARY_ANCHOR,
        SUMMARY_REPLACEMENT,
        "truncation summary",
    )
    for index, (old, new) in enumerate(PROMPT_REPLACEMENTS, start=1):
        prompt_source = replace_once(
            prompt_source, old, new, f"prompt pagination rule {index}"
        )

    operate_path.write_text(operate_source, encoding="utf-8")
    prompt_path.write_text(prompt_source, encoding="utf-8")
    print(f"installed: {operate_path}, {prompt_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operate_path", type=Path)
    parser.add_argument("prompt_path", type=Path)
    args = parser.parse_args()
    install(args.operate_path, args.prompt_path)


if __name__ == "__main__":
    main()
