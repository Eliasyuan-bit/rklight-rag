"""Safe reference previews and full-document Markdown reading pages."""
from __future__ import annotations

import asyncio
from html import escape
import re
from typing import Any

from lightrag.rk_reference_markdown import display_source_name


_CHUNK_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
MAX_PREVIEW_CHARS = 20_000
MAX_DOCUMENT_CHARS = 2_000_000


def valid_chunk_id(chunk_id: str) -> bool:
    return bool(_CHUNK_ID_RE.fullmatch(chunk_id))


def _section(chunk: dict[str, Any]) -> str | None:
    headings = chunk.get("content_headings")
    if isinstance(headings, str) and headings.strip():
        return headings.strip()[:300]
    if isinstance(headings, list):
        path = " > ".join(str(item).strip() for item in headings if str(item).strip())
        if path:
            return path[:300]
    for line in str(chunk.get("content") or "").splitlines():
        match = _HEADING_RE.match(line)
        if match:
            return match.group(1).strip(" *_`").strip()[:300] or None
    return None


def build_reference_preview(
    chunk_id: str,
    chunk: dict[str, Any],
    doc_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content = str(chunk.get("content") or "")
    file_path = str(chunk.get("file_path") or "")
    truncated = len(content) > MAX_PREVIEW_CHARS
    display_name = display_source_name(file_path) if file_path else "Unknown source"
    full_doc_id = str(chunk.get("full_doc_id") or "")
    track_id = str((doc_status or {}).get("track_id") or "")
    # Two selective-ingest variants share a track ID. Distinct uploads with
    # identical filenames must remain distinct in the evidence reader.
    source_group_id = f"{track_id}:{display_name}" if track_id else full_doc_id or chunk_id
    return {
        "chunk_id": chunk_id,
        "file_path": file_path,
        "display_name": display_name,
        "source_group_id": source_group_id,
        "section": _section(chunk),
        "content": content[:MAX_PREVIEW_CHARS],
        "truncated": truncated,
    }


async def group_footer_references(references: list[dict[str, Any]], rag: Any) -> list[dict[str, Any]]:
    """Resolve actual upload identities for the footer without merging namesakes.

    The API's evidence list and LLM-facing chunk IDs stay untouched. This is
    called after streamed tokens in the true-streaming path. Cache hits that
    return a single complete response resolve the groups before that response.
    Missing documents remain separate rather than being merged by filename.
    """
    chunk_ids = [str(ref.get("chunk_id") or "") for ref in references]
    chunks = await asyncio.gather(
        *(rag.text_chunks.get_by_id(chunk_id) if chunk_id else _empty_chunk() for chunk_id in chunk_ids),
        return_exceptions=True,
    )
    doc_ids = sorted({
        str(chunk.get("full_doc_id") or "")
        for chunk in chunks if isinstance(chunk, dict) and chunk.get("full_doc_id")
    })
    statuses = await asyncio.gather(
        *(rag.doc_status.get_by_id(doc_id) for doc_id in doc_ids),
        return_exceptions=True,
    )
    doc_statuses = dict(zip(doc_ids, statuses))
    result = []
    for ref, chunk in zip(references, chunks):
        updated = ref.copy()
        if isinstance(chunk, dict):
            doc_id = str(chunk.get("full_doc_id") or "")
            status = doc_statuses.get(doc_id)
            if not isinstance(status, dict):
                status = None
            updated["source_group_id"] = build_reference_preview(
                str(ref.get("chunk_id") or ""), chunk, status
            )["source_group_id"]
        result.append(updated)
    return result


async def _empty_chunk() -> None:
    return None


def _render_markdown(markdown: str) -> str:
    """Render Markdown with embedded HTML disabled; fall back to escaped source."""
    # Selective ingestion records the original name as an HTML comment. HTML
    # must remain disabled, but that one internal marker isn't reading text.
    markdown = re.sub(r"(?im)^[ \t]*<!--[ \t]*source:[^\n]*?-->[ \t]*\n?", "", markdown)
    try:
        from markdown_it import MarkdownIt

        return MarkdownIt("commonmark", {"html": False, "linkify": False}).render(markdown)
    except ImportError:
        return f"<pre>{escape(markdown)}</pre>"


def _split_cited_passage(document: str, passage: str) -> tuple[str, str, str] | None:
    passage = passage.strip()
    if not passage:
        return None
    offset = document.find(passage)
    if offset < 0:
        return None
    return document[:offset], passage, document[offset + len(passage) :]


def render_reference_document(
    chunk_id: str,
    chunk: dict[str, Any],
    full_doc: dict[str, Any] | None,
) -> str:
    """Return a standalone Markdown reader that highlights the cited passage."""
    file_path = str((full_doc or {}).get("file_path") or chunk.get("file_path") or "")
    title = display_source_name(file_path) if file_path else "引用文档"
    document = str((full_doc or {}).get("content") or chunk.get("content") or "")
    truncated = len(document) > MAX_DOCUMENT_CHARS
    document = document[:MAX_DOCUMENT_CHARS]
    passage = str(chunk.get("content") or "")
    split = _split_cited_passage(document, passage)

    if split:
        before, cited, after = split
        body = (
            _render_markdown(before)
            + '<section id="cited-passage" class="cited" aria-label="引用段落">'
            + '<div class="badge">引用段落</div>'
            + _render_markdown(cited)
            + "</section>"
            + _render_markdown(after)
        )
        location_note = "已定位回答引用的证据段落"
    else:
        body = (
            '<section id="cited-passage" class="cited" aria-label="引用段落">'
            '<div class="badge">引用段落（原文位置无法精确匹配）</div>'
            + _render_markdown(passage)
            + "</section>"
            + _render_markdown(document)
        )
        location_note = "引用内容与知识库全文无法精确对齐，已置顶显示"

    truncation_note = " · 文档过长，仅显示前 2,000,000 个字符" if truncated else ""
    safe_title = escape(title)
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:;">
  <title>{safe_title} · 引用</title>
  <style>
    :root {{ color-scheme:light; --bg:hsl(0 0% 100%); --fg:hsl(240 10% 3.9%); --muted:hsl(240 3.8% 46.1%); --line:hsl(240 5.9% 90%); --code:hsl(240 4.8% 95.9%); --cite:hsl(240 4.8% 95.9%); --cite-line:hsl(240 5.9% 10%); }}
    @media (prefers-color-scheme:dark) {{ :root:not(.rk-light) {{ color-scheme:dark; --bg:hsl(240 10% 3.9%); --fg:hsl(0 0% 98%); --muted:hsl(240 5% 64.9%); --line:hsl(240 3.7% 15.9%); --code:hsl(240 3.7% 15.9%); --cite:hsl(240 3.7% 15.9%); --cite-line:hsl(0 0% 98%); }} }}
    :root.rk-dark {{ color-scheme:dark; --bg:hsl(240 10% 3.9%); --fg:hsl(0 0% 98%); --muted:hsl(240 5% 64.9%); --line:hsl(240 3.7% 15.9%); --code:hsl(240 3.7% 15.9%); --cite:hsl(240 3.7% 15.9%); --cite-line:hsl(0 0% 98%); }}
    * {{ box-sizing:border-box }}
    body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.8 system-ui,-apple-system,"Segoe UI",sans-serif; overflow-wrap:anywhere; }}
    header {{ position:sticky; top:0; z-index:2; padding:16px max(24px,calc((100vw - 800px)/2)); background:var(--bg); border-bottom:1px solid var(--line); }}
    header strong {{ display:block; font-size:16px; overflow-wrap:anywhere }}
    header small {{ color:var(--muted) }}
    main {{ max-width:800px; margin:auto; padding:28px 36px 80px; }}
    h1,h2,h3,h4 {{ line-height:1.4; margin:1.5em 0 .6em; font-weight:650 }} h1 {{ border-bottom:1px solid var(--line); padding-bottom:.35em }}
    p {{ margin:0 0 1.1em }} ul,ol {{ padding-left:1.6em; margin:0 0 1.1em }} li {{ margin:.25em 0 }}
    pre {{ padding:16px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; background:var(--code); border-radius:9px }} code {{ background:var(--code); border-radius:4px; padding:.12em .3em }} pre code {{ padding:0 }}
    blockquote {{ margin-left:0; padding-left:16px; color:var(--muted); border-left:4px solid var(--line) }}
    a {{ color:var(--fg); text-decoration:underline; text-decoration-color:var(--muted) }} img {{ max-width:100% }} table {{ border-collapse:collapse; display:block; max-width:100%; overflow-x:auto }} th,td {{ border:1px solid var(--line); padding:6px 10px }}
    .cited {{ scroll-margin-top:30px; margin:24px -14px; padding:14px 18px; background:transparent; border-left:3px solid var(--cite-line); }}
    .cited > :last-child {{ margin-bottom:0 }} .cited > :nth-child(2) {{ margin-top:0 }}
    .badge {{ display:block; margin-bottom:8px; color:var(--muted); font-size:11px; font-weight:700; letter-spacing:.08em; }}
    @media (max-width:760px) {{ main {{ padding:16px 22px 64px }} .cited {{ margin:20px -8px; padding:12px 14px }} }}
  </style>
</head>
<body>
  <header><strong>{safe_title}</strong><small>{escape(location_note + truncation_note)}</small></header>
  <main>{body}</main>
</body>
</html>'''
