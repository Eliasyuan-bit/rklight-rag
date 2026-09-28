#!/usr/bin/env python3
"""Validate the structure and source balance of the three-document cases."""

from collections import Counter
import json
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parent
    dataset = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    errors = []
    cases = dataset.get("cases", [])
    sources = dataset.get("sources", {})
    seen = set()
    for case in cases:
        case_id = case.get("id")
        if not case_id or case_id in seen:
            errors.append(f"题号缺失或重复：{case_id}")
        seen.add(case_id)
        for field in ("source", "category", "question", "answerability", "expected", "forbidden", "format", "evidence"):
            if not case.get(field):
                errors.append(f"{case_id}: 缺少 {field}")
        if case.get("source") not in sources:
            errors.append(f"{case_id}: 未知 source {case.get('source')}")
        if case.get("answerability") not in {"answerable", "partial", "insufficient"}:
            errors.append(f"{case_id}: answerability 非法")
        for evidence in case.get("evidence", []):
            if not evidence.get("anchor") or not evidence.get("quote"):
                errors.append(f"{case_id}: evidence 缺少 anchor/quote")
    if len(cases) != 60:
        errors.append(f"期望 60 题，实际 {len(cases)} 题")
    expected_balance = {"ft": 20, "burn": 15, "sdk": 25}
    actual_balance = Counter(case.get("source") for case in cases)
    if dict(actual_balance) != expected_balance:
        errors.append(f"来源数量不符：{dict(actual_balance)}")
    result = {
        "case_count": len(cases),
        "source_balance": dict(actual_balance),
        "category_count": dict(Counter(case.get("category") for case in cases)),
        "errors": errors,
        "note": "结构校验通过不等于模型答案通过；答案仍需人工逐题核对。",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
