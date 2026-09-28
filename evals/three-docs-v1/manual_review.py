#!/usr/bin/env python3
"""Walk through the three-document RAG cases for manual WebUI review."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import random
import sys


ROOT = Path(__file__).resolve().parent


def load_cases():
    return json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))


def print_case(case, position, total, reveal=False):
    print(f"\n[{position}/{total}] {case['id']}  {case['source']} / {case['category']}")
    print(f"问题：{case['question']}")
    if not reveal:
        return
    print("\n预期答案要点：")
    for item in case["expected"]:
        print(f"  - {item}")
    print("不应出现：")
    for item in case["forbidden"]:
        print(f"  - {item}")
    print(f"格式要求：{case['format']}")
    print("证据定位：")
    for item in case["evidence"]:
        print(f"  - {item['anchor']}：{item['quote']}")


def save_session(path, dataset, selected, reviews, started_at):
    payload = {
        "dataset_version": dataset["version"],
        "started_at": started_at,
        "updated_at": datetime.now().astimezone().isoformat(),
        "selected_case_ids": [case["id"] for case in selected],
        "reviews": reviews,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["ft", "burn", "sdk"], help="只测试一个文档")
    parser.add_argument("--ids", nargs="+", help="只测试指定题号")
    parser.add_argument("--start", help="从指定题号开始")
    parser.add_argument("--shuffle", action="store_true", help="随机题序")
    parser.add_argument("--seed", type=int, default=20260918)
    parser.add_argument("--questions-only", action="store_true", help="打印问题清单后退出")
    parser.add_argument("--with-answers", action="store_true", help="清单同时打印验收答案")
    parser.add_argument("--output", help="人工结果 JSON 路径")
    args = parser.parse_args()

    dataset = load_cases()
    selected = list(dataset["cases"])
    if args.source:
        selected = [case for case in selected if case["source"] == args.source]
    if args.ids:
        wanted = set(args.ids)
        unknown = sorted(wanted - {case["id"] for case in dataset["cases"]})
        if unknown:
            parser.error("未知题号：" + ", ".join(unknown))
        selected = [case for case in selected if case["id"] in wanted]
    if args.start:
        starts = [index for index, case in enumerate(selected) if case["id"] == args.start]
        if not starts:
            parser.error(f"起始题不在当前选择中：{args.start}")
        selected = selected[starts[0]:]
    if args.shuffle:
        random.Random(args.seed).shuffle(selected)
    if not selected:
        parser.error("没有匹配的题目")

    if args.questions_only or args.with_answers:
        for index, case in enumerate(selected, 1):
            print_case(case, index, len(selected), reveal=args.with_answers)
        return 0

    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    output = Path(args.output) if args.output else ROOT / "results" / f"manual-{timestamp}.json"
    started_at = datetime.now().astimezone().isoformat()
    reviews = []
    print(f"共 {len(selected)} 题。把‘问题’复制到网页，每题使用空历史会话。")
    print("看到网页完整回答后按 Enter 揭示标准；评分输入 p=通过、f=失败、s=跳过、q=保存退出。")

    for index, case in enumerate(selected, 1):
        print_case(case, index, len(selected), reveal=False)
        try:
            input("\n网页回答完成后按 Enter 查看验收点...")
        except (EOFError, KeyboardInterrupt):
            print("\n已中止。")
            break
        print_case(case, index, len(selected), reveal=True)
        while True:
            verdict = input("\n评分 [p/f/s/q]：").strip().lower()
            if verdict in {"p", "f", "s", "q"}:
                break
            print("请输入 p、f、s 或 q。")
        if verdict == "q":
            break
        note = input("备注（可留空）：").strip()
        reviews.append({
            "case_id": case["id"],
            "verdict": {"p": "pass", "f": "fail", "s": "skip"}[verdict],
            "note": note,
        })
        save_session(output, dataset, selected, reviews, started_at)

    save_session(output, dataset, selected, reviews, started_at)
    counts = {name: sum(item["verdict"] == name for item in reviews) for name in ("pass", "fail", "skip")}
    print(f"\n结果已保存：{output}")
    print(f"完成 {len(reviews)}/{len(selected)}，通过 {counts['pass']}，失败 {counts['fail']}，跳过 {counts['skip']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
