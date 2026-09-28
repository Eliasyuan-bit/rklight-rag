#!/usr/bin/env python3
"""Run the three-document evaluation against a board-local LightRAG server."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import statistics
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from evidence_baseline import empty_review, trace_id


ROOT = Path(__file__).resolve().parent
SMOKE_IDS = ["FT02", "FT11", "BURN01", "BURN08", "BURN11", "SDK08", "SDK09", "SDK16", "SDK22"]


def post_stream(url, payload, timeout):
    request = Request(
        url.rstrip("/") + "/query/stream",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/x-ndjson"},
        method="POST",
    )
    started = time.monotonic()
    answer_parts, references, progress = [], [], []
    ttft_ms = None
    status = None
    error = None
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    error = f"invalid NDJSON event: {line[:160]}"
                    continue
                if event.get("progress"):
                    progress.append(event["progress"])
                if "references" in event:
                    references = event.get("references") or []
                if event.get("response"):
                    if ttft_ms is None:
                        ttft_ms = round((time.monotonic() - started) * 1000, 1)
                    answer_parts.append(event["response"])
                if event.get("error"):
                    error = str(event["error"])
    except HTTPError as exc:
        status = exc.code
        error = exc.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError) as exc:
        error = str(exc)
    return {
        "answer": "".join(answer_parts).strip(),
        "references": references,
        "progress": progress,
        "ttft_ms": ttft_ms,
        "total_ms": round((time.monotonic() - started) * 1000, 1),
        "http_status": status,
        "error": error,
    }


def markdown_report(run):
    lines = [
        "# 三文档 RAG 板端测试报告", "",
        f"- Run ID: `{run['run_id']}`",
        f"- Started: {run['started_at']}",
        f"- URL: `{run['url']}`",
        f"- Mode: `{run['query_config']['mode']}`",
        f"- Progress: {len(run['results'])}/{run['requested']}", "",
    ]
    for item in run["results"]:
        state = "完成" if not item["error"] else f"ERROR: {item['error']}"
        lines.extend([
            f"## {item['case_id']} · {item['question']}", "",
            f"- 状态：{state}",
            f"- TTFT：{item['ttft_ms']} ms",
            f"- 总耗时：{item['total_ms']} ms", "",
            "### 实际回答", "", item["answer"] or "（无回答）", "",
            "### 预期答案要点", "",
        ])
        lines.extend(f"- {value}" for value in item["expected"])
        lines.extend(["", "### 不应出现", ""])
        lines.extend(f"- {value}" for value in item["forbidden"])
        lines.extend(["", "### API References", ""])
        if item["references"]:
            lines.extend(["```json", json.dumps(item["references"], ensure_ascii=False, indent=2), "```"])
        else:
            lines.append("（无）")
        review = item.get("assessment") or empty_review()
        lines.extend([
            "", "### 证据级人工结论", "",
            f"- 正确章节/表格进入候选：`{review.get('retrieval_hit', 'unknown')}`",
            f"- 最终证据字段完整：`{review.get('evidence_complete', 'unknown')}`",
            f"- 回答被引用支持：`{review.get('grounded', 'unknown')}`",
            f"- 最终答案正确：`{review.get('answer_correct', 'unknown')}`",
            f"- 主要失败原因：`{review.get('primary_failure', 'not_reviewed')}`",
            f"- 备注：{review.get('notes', '')}",
            "",
        ])
    if run.get("summary"):
        lines.extend(["## 汇总", "", "```json", json.dumps(run["summary"], ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9621")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--smoke", action="store_true", help="运行 9 题冒烟集")
    selection.add_argument("--source", choices=["ft", "burn", "sdk"], help="只跑一个文档")
    selection.add_argument("--ids", nargs="+", help="只跑指定题号")
    parser.add_argument("--limit", type=int, help="只跑前 N 题")
    parser.add_argument("--mode", choices=["local", "global", "hybrid", "naive", "mix", "bypass"], default="mix")
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--chunk-top-k", type=int, default=3)
    parser.add_argument("--max-entity-tokens", type=int, default=500)
    parser.add_argument("--max-relation-tokens", type=int, default=300)
    parser.add_argument("--max-total-tokens", type=int, default=3000)
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--output", help="结果 JSON 路径；同时生成同名 .md")
    parser.add_argument("--label", default="board")
    parser.add_argument("--dry-run", action="store_true", help="只显示题目，不请求 RAG")
    args = parser.parse_args()

    dataset = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    all_cases = dataset["cases"]
    by_id = {case["id"]: case for case in all_cases}
    if args.smoke:
        selected = [by_id[case_id] for case_id in SMOKE_IDS]
    elif args.source:
        selected = [case for case in all_cases if case["source"] == args.source]
    elif args.ids:
        unknown = [case_id for case_id in args.ids if case_id not in by_id]
        if unknown:
            parser.error("未知题号：" + ", ".join(unknown))
        selected = [by_id[case_id] for case_id in args.ids]
    else:
        selected = all_cases
    if args.limit is not None:
        if args.limit <= 0:
            parser.error("--limit 必须大于 0")
        selected = selected[:args.limit]
    if args.dry_run:
        for case in selected:
            print(f"{case['id']}\t{case['source']}\t{case['question']}")
        print(f"共 {len(selected)} 题")
        return 0

    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S%z")
    run_id = f"{args.label}-{timestamp}"
    output = Path(args.output) if args.output else ROOT / "results" / f"{run_id}.json"
    report = output.with_suffix(".md")
    output.parent.mkdir(parents=True, exist_ok=True)
    query_config = {
        "mode": args.mode,
        "stream": True,
        "include_references": True,
        "include_chunk_content": True,
        "include_progress": True,
        "enable_rerank": not args.no_rerank,
        "top_k": args.top_k,
        "chunk_top_k": args.chunk_top_k,
        "max_entity_tokens": args.max_entity_tokens,
        "max_relation_tokens": args.max_relation_tokens,
        "max_total_tokens": args.max_total_tokens,
        "conversation_history": [],
    }
    run = {
        "run_id": run_id,
        "dataset_version": dataset["version"],
        "started_at": datetime.now().astimezone().isoformat(),
        "url": args.url,
        "query_config": query_config,
        "requested": len(selected),
        "results": [],
    }

    def persist():
        output.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report.write_text(markdown_report(run), encoding="utf-8")

    persist()
    for index, case in enumerate(selected, 1):
        print(f"[{index}/{len(selected)}] {case['id']} {case['question']}", flush=True)
        measured = post_stream(args.url, {"query": case["question"], **query_config}, args.timeout)
        run["results"].append({
            "case_id": case["id"], "source": case["source"], "category": case["category"],
            "question": case["question"], "expected": case["expected"],
            "forbidden": case["forbidden"], "format": case["format"],
            "evidence": case["evidence"],
            "expected_source": dataset["sources"][case["source"]]["file"],
            "retrieval_trace_id": trace_id(case["question"]),
            "assessment": empty_review(),
            **measured,
        })
        persist()
        state = "ERROR" if measured["error"] else "OK"
        print(f"  {state} TTFT={measured['ttft_ms']}ms total={measured['total_ms']}ms refs={len(measured['references'])}", flush=True)

    valid = [item for item in run["results"] if not item["error"]]
    ttfts = [item["ttft_ms"] for item in valid if item["ttft_ms"] is not None]
    totals = [item["total_ms"] for item in valid]
    run["finished_at"] = datetime.now().astimezone().isoformat()
    run["summary"] = {
        "requested": len(selected),
        "completed_without_api_error": len(valid),
        "errors": len(selected) - len(valid),
        "ttft_ms_median": round(statistics.median(ttfts), 1) if ttfts else None,
        "ttft_ms_p95": percentile(ttfts, 0.95),
        "total_ms_median": round(statistics.median(totals), 1) if totals else None,
        "total_ms_p95": percentile(totals, 0.95),
        "quality_note": "正确性需在 Markdown 报告中人工勾选，脚本不按关键词自动判分。",
    }
    persist()
    print(f"JSON: {output}")
    print(f"人工审核报告: {report}")
    print(json.dumps(run["summary"], ensure_ascii=False, indent=2))
    return 1 if run["summary"]["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
