#!/usr/bin/env python3
"""Create an evidence-level baseline report from a three-document eval run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evidence_baseline import assessment_for_item, hydrate_item, summarize


def markdown_report(run: dict[str, Any], summary: dict[str, Any]) -> str:
    lines = [
        "# 三文档 RAG 证据级基线报告",
        "",
        f"- Run ID: `{run.get('run_id', 'unknown')}`",
        f"- Source run: `{run.get('_source_path', 'unknown')}`",
        "- 说明：自动字段只描述 API 可观察事实；检索命中、证据完整性、引用支持和答案正确性必须由人工审核。",
        "",
        "## 汇总",
        "",
        "```json",
        json.dumps(summary, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 逐题证据状态",
        "",
        "| ID | API | 预期源被引 | 可见必需引文 | 召回 | 证据完整 | 有据 | 正确 | 主失败 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in run.get("results", []):
        assessment = assessment_for_item(item)
        automatic = assessment["automatic"]
        review = assessment["review"]
        source_cited = automatic["expected_source_cited"]
        lines.append(
            "| {id} | {api} | {source} | {quotes} | {retrieval} | {evidence} | {grounded} | {correct} | {failure} |".format(
                id=item.get("case_id", "?"),
                api="pass" if automatic["api_ok"] else "fail",
                source="pass" if source_cited else ("fail" if source_cited is False else "unknown"),
                quotes=automatic["final_evidence_visible"],
                retrieval=review["retrieval_hit"],
                evidence=review["evidence_complete"],
                grounded=review["grounded"],
                correct=review["answer_correct"],
                failure=review["primary_failure"],
            )
        )
    lines.extend([
        "",
        "## 判定规则",
        "",
        "- `retrieval_miss`：正确章节/表格未进入候选；",
        "- `context_loss`：正确证据进入候选，但没有进入最终生成证据；",
        "- `evidence_insufficient`：最终证据存在但缺少回答所需字段；",
        "- `generation_error`：最终证据完整且回答仍错误；",
        "- `api_error`：请求、流式响应或模型服务失败；",
        "- `not_reviewed`：尚未人工分类，不能用于计算正确率。",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="run_eval.py 生成的 JSON，可为已审核副本")
    parser.add_argument("--output", type=Path, help="输出 JSON；默认写到输入文件同目录")
    args = parser.parse_args()

    run = json.loads(args.run.read_text(encoding="utf-8"))
    dataset_path = Path(__file__).with_name("cases.json")
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in dataset["cases"]}
    source_files = {name: source["file"] for name, source in dataset["sources"].items()}
    for item in run.get("results", []):
        case = by_id.get(item.get("case_id"))
        if case:
            hydrate_item(item, case, source_files)
    run["_source_path"] = str(args.run)
    summary = summarize(run.get("results", []))
    output = args.output or args.run.with_name(args.run.stem + "-baseline.json")
    markdown = output.with_suffix(".md")
    output.write_text(
        json.dumps({"run_id": run.get("run_id"), "source_run": str(args.run), "summary": summary}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    markdown.write_text(markdown_report(run, summary), encoding="utf-8")
    print(f"JSON: {output}")
    print(f"Markdown: {markdown}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
