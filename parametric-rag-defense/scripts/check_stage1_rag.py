#!/usr/bin/env python3
"""Check normalized RAG artifact coverage and task identity for one execution tier."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parametric_rag_defense.matrix import build_rag_tasks
from parametric_rag_defense.rag_artifacts import artifact_path, normalize_record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument("--tier", choices=("development_sweep", "locked_primary", "locked_strength_curve"), required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    tier = config["execution_tiers"][args.tier]
    split = json.loads(Path(config["dataset"]["split_manifest"]).read_text(encoding="utf-8"))
    tasks = build_rag_tasks(config, args.tier, split[tier["split"]]["claim_ids"])
    root = Path(config["run_root"]) / tier["split"] / "rag_endpoint"
    problems: list[str] = []
    for task in tasks:
        path = artifact_path(root, task["task_key"])
        if not path.exists():
            problems.append(f"missing {task['task_key']}")
            continue
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
            record = {
                "task_key": artifact["task_key"],
                "judgment": artifact["judgment"],
                "audit": artifact["audit"],
                "provenance": artifact["provenance"],
            }
            rebuilt = normalize_record(record, task)
            if rebuilt != artifact:
                problems.append(f"non-canonical {task['task_key']}")
        except Exception as exc:
            problems.append(f"invalid {task['task_key']}: {exc}")
    if problems:
        print(f"Stage 1 RAG completeness FAILED: {len(problems)} problem(s) / {len(tasks)} tasks")
        for problem in problems[:25]:
            print(f"- {problem}")
        if len(problems) > 25:
            print(f"- ... {len(problems)-25} more")
        raise SystemExit(1)
    print(f"Stage 1 RAG completeness passed: tier={args.tier} tasks={len(tasks)}")


if __name__ == "__main__":
    main()
