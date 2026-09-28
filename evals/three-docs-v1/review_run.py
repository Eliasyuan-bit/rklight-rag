#!/usr/bin/env python3
"""Classify evidence-level failure causes in an existing board evaluation run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evidence_baseline import ASSESSMENT_VALUES, FAILURE_TYPES, assessment_for_item, hydrate_item, normalize_review


VALUE_HELP = "p=pass, f=fail, ?=unknown, q=save and quit"
FAILURE_HELP = (
    "p=pass, r=retrieval_miss, c=context_loss, e=evidence_insufficient, "
    "g=generation_error, a=api_error, n=not_reviewed"
)
VALUE_MAP = {"p": "pass", "f": "fail", "?": "unknown"}
FAILURE_MAP = {
    "p": "pass", "r": "retrieval_miss", "c": "context_loss",
    "e": "evidence_insufficient", "g": "generation_error", "a": "api_error", "n": "not_reviewed",
}


def prompt(label: str, values: tuple[str, ...], current: str, help_text: str) -> str | None:
    while True:
        raw = input(f"{label} [{current}] ({help_text})：").strip().lower()
        if raw == "q":
            return None
        if not raw:
            return current
        mapping = VALUE_MAP if values == ASSESSMENT_VALUES else FAILURE_MAP
        if raw in mapping:
            return mapping[raw]
        print("输入无效。")


def save(path: Path, run: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="run_eval.py 生成的结果 JSON")
    parser.add_argument("--output", type=Path, help="审核副本；默认 <run>-reviewed.json")
    parser.add_argument("--ids", nargs="+", help="只审核指定题号")
    args = parser.parse_args()
    run = json.loads(args.run.read_text(encoding="utf-8"))
    dataset_path = Path(__file__).with_name("cases.json")
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in dataset["cases"]}
    source_files = {name: source["file"] for name, source in dataset["sources"].items()}
    output = args.output or args.run.with_name(args.run.stem + "-reviewed.json")
    wanted = set(args.ids or [])

    for item in run.get("results", []):
        case = by_id.get(item.get("case_id"))
        if case:
            hydrate_item(item, case, source_files)
        if wanted and item.get("case_id") not in wanted:
            continue
        state = assessment_for_item(item)
        automatic, review = state["automatic"], state["review"]
        print("\n" + "=" * 72)
        print(f"{item.get('case_id')} · {item.get('question')}")
        print(f"自动：api_ok={automatic['api_ok']} expected_source_cited={automatic['expected_source_cited']} visible_quotes={automatic['visible_evidence_quote_hits']}/{automatic['visible_evidence_quote_total']}")
        print("回答：\n" + (item.get("answer") or "（无回答）"))
        print("预期：" + "；".join(item.get("expected") or []))
        print("禁止：" + "；".join(item.get("forbidden") or []))
        print("引用：" + "，".join(automatic["cited_sources"]))
        for field, label in (
            ("retrieval_hit", "正确章节/表格进入候选"),
            ("evidence_complete", "最终证据字段完整"),
            ("grounded", "回答被引用支持"),
            ("answer_correct", "最终答案正确"),
        ):
            value = prompt(label, ASSESSMENT_VALUES, review[field], VALUE_HELP)
            if value is None:
                save(output, run)
                print(f"已保存：{output}")
                return 0
            review[field] = value
        failure = prompt("主要失败原因", FAILURE_TYPES, review["primary_failure"], FAILURE_HELP)
        if failure is None:
            save(output, run)
            print(f"已保存：{output}")
            return 0
        review["primary_failure"] = failure
        review["notes"] = input("备注（可留空）：").strip()
        item["assessment"] = normalize_review(review)
        save(output, run)

    save(output, run)
    print(f"已保存：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
