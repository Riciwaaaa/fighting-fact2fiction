#!/usr/bin/env python3
"""Materialize Stage 1 task manifests and a compact workload summary."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from parametric_rag_defense.matrix import (
    all_attack_conditions,
    build_internal_tasks,
    build_rag_tasks,
)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/runs/stage1/task_matrix"))
    parser.add_argument(
        "--summary-output", type=Path, default=Path("configs/stage1_task_summary.json")
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    split = json.loads(Path(config["dataset"]["split_manifest"]).read_text(encoding="utf-8"))
    output = args.output.resolve()

    internal_counts: dict[str, int] = {}
    enabled_internal_counts: dict[str, int] = {}
    enabled_model_ids = {
        model["id"] for model in config["models"] if model.get("enabled", True)
    }
    for split_name in ("development", "locked_test"):
        tasks = build_internal_tasks(config, split_name, split[split_name]["claim_ids"])
        atomic_jsonl(output / f"internal_{split_name}.jsonl", tasks)
        internal_counts[split_name] = len(tasks)
        enabled_internal_counts[split_name] = sum(
            task["model_id"] in enabled_model_ids for task in tasks
        )

    rag_counts: dict[str, int] = {}
    enabled_rag_counts: dict[str, int] = {}
    unique_rag_keys: set[str] = set()
    unique_enabled_rag_keys: set[str] = set()
    for tier_name, tier in config["execution_tiers"].items():
        claim_ids = split[tier["split"]]["claim_ids"]
        tasks = build_rag_tasks(config, tier_name, claim_ids)
        atomic_jsonl(output / f"rag_{tier_name}.jsonl", tasks)
        rag_counts[tier_name] = len(tasks)
        enabled_rag_counts[tier_name] = sum(
            task["model_id"] in enabled_model_ids for task in tasks
        )
        unique_rag_keys.update(task["task_key"] for task in tasks)
        unique_enabled_rag_keys.update(
            task["task_key"] for task in tasks if task["model_id"] in enabled_model_ids
        )

    conditions = all_attack_conditions(config)
    summary = {
        "summary_schema_version": 2,
        "models": [model["id"] for model in config["models"]],
        "model_count": len(config["models"]),
        "enabled_models": sorted(enabled_model_ids),
        "enabled_model_count": len(enabled_model_ids),
        "conditions": conditions,
        "condition_count": len(conditions),
        "internal_task_counts": internal_counts,
        "enabled_internal_task_counts": enabled_internal_counts,
        "rag_task_counts_by_tier": rag_counts,
        "enabled_rag_task_counts_by_tier": enabled_rag_counts,
        "unique_rag_tasks_across_tiers": len(unique_rag_keys),
        "unique_enabled_rag_tasks_across_tiers": len(unique_enabled_rag_keys),
        "rag_counts_are_prefilter_upper_bounds": True,
        "eligibility_note": (
            "Generate clean RAG outputs first, then apply Fact2Fiction's clean-correct filter "
            "per victim before scheduling attacked tasks."
        ),
        "reuse_note": "Internal tasks do not multiply by attack condition; their cache keys are reused.",
    }
    atomic_json(args.summary_output.resolve(), summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
