#!/usr/bin/env python3
"""Validate evaluation structure and optionally check quotes against a corpus export.

Reads only; never contacts the RAG service or modifies the knowledge base.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


def digest(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", help="kv_store_full_docs.json path, or - for stdin")
    args = parser.parse_args()
    dataset = json.loads(Path(__file__).with_name("cases.json").read_text())
    cases, sources = dataset["cases"], dataset["sources"]
    errors = []
    seen = set()
    for case in cases:
        cid = case["id"]
        if cid in seen:
            errors.append(f"duplicate ID: {cid}")
        seen.add(cid)
        for field in ("question", "category", "origin", "expected", "forbidden", "format"):
            if not case.get(field):
                errors.append(f"{cid}: missing {field}")
        if case["answerability"] not in ("answerable", "partial", "insufficient"):
            errors.append(f"{cid}: invalid answerability")
        if case["answerability"] != "insufficient" and not case["evidence"]:
            errors.append(f"{cid}: missing evidence")
        for evidence in case["evidence"]:
            if evidence["source"] not in sources or not evidence.get("quote") or not evidence.get("anchor"):
                errors.append(f"{cid}: invalid evidence")
    if len(cases) != 40:
        errors.append(f"expected 40 cases, got {len(cases)}")

    snapshot = None
    if args.corpus:
        if args.corpus == "-":
            corpus = json.load(sys.stdin)
        else:
            corpus = json.loads(Path(args.corpus).read_text())
        snapshot = {
            doc_id: {"file": doc.get("file_path"), "content_sha256": digest(doc["content"])}
            for doc_id, doc in sorted(corpus.items())
        }
        for alias, source in sources.items():
            doc = corpus.get(source["doc_id"])
            if doc is None:
                errors.append(f"missing source: {alias}")
            elif doc.get("file_path") != source["file"]:
                errors.append(f"source filename changed: {alias}")
        for case in cases:
            for evidence in case["evidence"]:
                source = sources.get(evidence["source"], {})
                doc = corpus.get(source.get("doc_id"), {})
                if evidence["quote"] not in doc.get("content", ""):
                    errors.append(f"{case['id']}: quote absent in {evidence['source']}: {evidence['quote']!r}")

    print(json.dumps({
        "case_count": len(cases),
        "answerability": dict(Counter(c["answerability"] for c in cases)),
        "origins": dict(Counter(c["origin"] for c in cases)),
        "evidence_count": sum(len(c["evidence"]) for c in cases),
        "corpus_quotes_checked": args.corpus is not None,
        "corpus_snapshot": snapshot,
        "errors": errors,
        "note": "Quote presence is not a semantic correctness or citation-support score.",
    }, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
