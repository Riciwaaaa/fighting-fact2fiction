#!/usr/bin/env python3
"""Validate and immutably ingest normalized RAG endpoint JSONL records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parametric_rag_defense.matrix import build_rag_tasks
from parametric_rag_defense.rag_artifacts import normalize_record, store_immutable


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSONL records following docs/STAGE1_EXECUTION.md")
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument("--tier", choices=("development_sweep", "locked_primary", "locked_strength_curve"), required=True)
    parser.add_argument("--allow-locked-test", action="store_true")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    tier = config["execution_tiers"][args.tier]
    if tier["split"] == "locked_test" and not args.allow_locked_test:
        raise SystemExit("Refusing to ingest locked test artifacts without --allow-locked-test")
    split = json.loads(Path(config["dataset"]["split_manifest"]).read_text(encoding="utf-8"))
    tasks = build_rag_tasks(config, args.tier, split[tier["split"]]["claim_ids"])
    expected = {task["task_key"]: task for task in tasks}
    root = Path(config["run_root"]) / tier["split"] / "rag_endpoint"

    seen: set[str] = set()
    written = 0
    cached = 0
    with args.input.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            task_key = record.get("task_key") if isinstance(record, dict) else None
            if task_key not in expected:
                raise SystemExit(f"line {line_number}: task_key is not expected for tier {args.tier}")
            if task_key in seen:
                raise SystemExit(f"line {line_number}: duplicate task_key in input")
            seen.add(task_key)
            artifact = normalize_record(record, expected[task_key])
            _, already_present = store_immutable(root, artifact)
            cached += int(already_present)
            written += int(not already_present)
    print(
        f"ingested tier={args.tier} records={len(seen)} written={written} "
        f"already_present={cached} root={root.resolve()}"
    )


if __name__ == "__main__":
    main()
