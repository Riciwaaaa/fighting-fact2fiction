#!/usr/bin/env python3
"""Report model-only/RAG complementarity in imported development-only artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path("artifacts/legacy/run05_stage1"),
    )
    args = parser.parse_args()
    artifact_dir = args.artifact_dir.resolve()
    rows = [json.loads(line) for line in (artifact_dir / "endpoints.jsonl").read_text().splitlines()]
    label_record = json.loads((artifact_dir / "evaluation_labels.json").read_text())
    labels = label_record["labels"]

    counts = {"both_correct": 0, "internal_only": 0, "rag_only": 0, "both_wrong": 0}
    complete = 0
    for row in rows:
        gold = labels.get(str(row["claim_id"]))
        internal = row["internal_endpoint"]["verdict"]
        rag = row["rag_endpoint"]["verdict"]
        if not gold or not internal or not rag:
            continue
        complete += 1
        internal_correct = internal == gold
        rag_correct = rag == gold
        if internal_correct and rag_correct:
            counts["both_correct"] += 1
        elif internal_correct:
            counts["internal_only"] += 1
        elif rag_correct:
            counts["rag_only"] += 1
        else:
            counts["both_wrong"] += 1

    internal_correct = counts["both_correct"] + counts["internal_only"]
    rag_correct = counts["both_correct"] + counts["rag_only"]
    oracle_correct = internal_correct + counts["rag_only"]
    disagreement = counts["internal_only"] + counts["rag_only"]

    print(f"complete={complete}")
    for name, value in counts.items():
        print(f"{name}={value}")
    print(f"internal_accuracy={internal_correct / complete:.4f}")
    print(f"rag_accuracy={rag_correct / complete:.4f}")
    print(f"oracle_accuracy={oracle_correct / complete:.4f}")
    print(f"disagreements={disagreement}")
    print(f"always_internal_on_disagreement={counts['internal_only'] / disagreement:.4f}")


if __name__ == "__main__":
    main()

