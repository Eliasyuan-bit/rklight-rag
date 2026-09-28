#!/usr/bin/env python3
"""Merge segmented three-document eval runs into one ordered baseline run.

Inputs are applied in order.  A later result with the same case ID replaces an
earlier result, which makes clean reruns replace transient timeout attempts.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from evidence_baseline import hydrate_item, summarize


ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path, help="按时间顺序给出的 run JSON")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--label", default="baseline-merged")
    args = parser.parse_args()

    dataset = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    source_files = {name: source["file"] for name, source in dataset["sources"].items()}
    cases = {case["id"]: case for case in dataset["cases"]}
    merged: dict[str, dict] = {}
    source_runs = []
    for path in args.runs:
        run = json.loads(path.read_text(encoding="utf-8"))
        source_runs.append({"path": str(path), "run_id": run.get("run_id")})
        for item in run.get("results", []):
            case_id = item.get("case_id")
            case = cases.get(case_id)
            if not case:
                raise SystemExit(f"未知题号 {case_id!r}：{path}")
            hydrate_item(item, case, source_files)
            merged[case_id] = item
    missing = [case_id for case_id in cases if case_id not in merged]
    if missing:
        raise SystemExit("合并后仍缺题：" + ", ".join(missing))

    ordered = [merged[case["id"]] for case in dataset["cases"]]
    output = {
        "run_id": args.label + "-" + datetime.now().astimezone().strftime("%Y%m%d-%H%M%S%z"),
        "dataset_version": dataset["version"],
        "created_at": datetime.now().astimezone().isoformat(),
        "source_runs": source_runs,
        "requested": len(ordered),
        "results": ordered,
        "summary": summarize(ordered),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"merged {len(ordered)} cases: {args.output}")
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
