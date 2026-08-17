#!/usr/bin/env python3
"""Evaluate the frozen matched-control and fixed-context stress arbiters."""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json

CONDITIONS = (
    "clean",
    "fact2fiction_p0.001",
    "fact2fiction_p0.0025",
    "fact2fiction_p0.005",
)
SYSTEMS = ("rag", "memory", "champion", "control", "full", "oracle")


def identity(row: dict[str, Any]) -> tuple[str, int, str]:
    return row["victim_model_id"], int(row["claim_id"]), row["condition_id"]


def apply_action(row: dict[str, Any], action: str) -> str:
    if action == "trust_rag":
        return row["rag_prediction"]
    if action == "trust_memory":
        return row["memory_prediction"]
    if action == "keep_champion":
        return row["champion_prediction"]
    raise ValueError(f"Unknown arbiter action: {action}")


def exact_paired_pvalue(left_only: int, right_only: int) -> float:
    discordant = left_only + right_only
    if not discordant:
        return 1.0
    tail = sum(
        math.comb(discordant, value)
        for value in range(min(left_only, right_only) + 1)
    )
    return min(1.0, 2.0 * tail / (2**discordant))


def bootstrap_delta(
    rows: list[dict[str, Any]], left: str, right: str
) -> list[float]:
    by_claim: dict[int, list[int]] = {}
    for row in rows:
        by_claim.setdefault(int(row["claim_id"]), []).append(
            int(row[f"{left}_correct"]) - int(row[f"{right}_correct"])
        )
    if not by_claim:
        return [0.0, 0.0]
    claims = sorted(by_claim)
    rng = random.Random(20260812)
    samples = []
    for _ in range(5000):
        selected = rng.choices(claims, k=len(claims))
        deltas = [value for claim in selected for value in by_claim[claim]]
        samples.append(sum(deltas) / len(deltas))
    samples.sort()
    return [samples[125], samples[4874]]


def compare(rows: list[dict[str, Any]], left: str, right: str) -> dict[str, Any]:
    left_only = sum(
        row[f"{left}_correct"] and not row[f"{right}_correct"] for row in rows
    )
    right_only = sum(
        row[f"{right}_correct"] and not row[f"{left}_correct"] for row in rows
    )
    return {
        "left_only_correct": left_only,
        "right_only_correct": right_only,
        "net": left_only - right_only,
        "exact_p": exact_paired_pvalue(left_only, right_only),
        "claim_cluster_bootstrap95_accuracy_delta": bootstrap_delta(rows, left, right),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {
        "rows": len(rows),
        "systems": {
            system: {
                "correct": sum(row[f"{system}_correct"] for row in rows),
                "accuracy": (
                    sum(row[f"{system}_correct"] for row in rows) / len(rows)
                    if rows
                    else None
                ),
            }
            for system in SYSTEMS
        },
        "comparisons": {
            f"{left}_vs_{right}": compare(rows, left, right)
            for left, right in (
                ("control", "champion"),
                ("full", "champion"),
                ("full", "control"),
                ("full", "rag"),
                ("full", "memory"),
            )
        },
        "actions": {
            variant: dict(
                sorted(Counter(row[f"{variant}_action"] for row in rows).items())
            )
            for variant in ("control", "full")
        },
    }
    return result


def read_usage(cache_root: Path, cache_keys: set[str]) -> dict[str, int]:
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for key in cache_keys:
        entry = json.loads(
            (cache_root / "entries" / key[:2] / f"{key}.json").read_text()
        )
        usage = entry["response"].get("usage") or {}
        for field in totals:
            totals[field] += int(usage.get(field) or 0)
    return totals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("artifacts/runs/rag_stress_arbiter/rag_stress_arbiter_v1"),
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=Path("artifacts/evaluation/counter_retrieval_signal_v2.json"),
    )
    parser.add_argument(
        "--cache-root", type=Path, default=Path("artifacts/cache/llm")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluation/rag_stress_arbiter_v1.json"),
    )
    args = parser.parse_args()

    manifest = json.loads((args.run_root / "private_manifest.json").read_text())
    if (
        manifest.get("failures")
        or manifest.get("completed_outputs") != 454
        or manifest.get("binary_endpoint_rows") != 227
    ):
        raise ValueError("Frozen stress-arbiter run is incomplete")
    base = json.loads(args.base.read_text())
    base_by_id = {identity(row): row for row in base["private_rows"]}
    outputs: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    cache_keys = set()
    for descriptor in manifest["rows"]:
        key = (descriptor["variant"], *identity(descriptor))
        if key in outputs:
            raise ValueError(f"Duplicate arbiter identity: {key}")
        outputs[key] = json.loads(Path(descriptor["output_path"]).read_text())[
            "judgment"
        ]
        cache_keys.add(descriptor["arbiter_cache_key"])

    rows = []
    for descriptor in manifest["rows"]:
        if descriptor["variant"] != "full":
            continue
        row_id = identity(descriptor)
        base_row = base_by_id[row_id]
        if {descriptor["rag_prediction"], descriptor["memory_prediction"]} != {
            "Supported",
            "Refuted",
        }:
            raise ValueError(f"Non-exclusive endpoint row in arbiter scope: {row_id}")
        row = {
            **base_row,
            "champion_prediction": descriptor["champion_prediction"],
        }
        for variant in ("control", "full"):
            judgment = outputs[(variant, *row_id)]
            row[f"{variant}_action"] = judgment["action"]
            row[f"{variant}_confidence"] = judgment["confidence"]
            row[f"{variant}_prediction"] = apply_action(row, judgment["action"])
        row["oracle_prediction"] = (
            row["rag_prediction"]
            if row["rag_prediction"] == row["gold"]
            else row["memory_prediction"]
        )
        for system in SYSTEMS:
            row[f"{system}_correct"] = row[f"{system}_prediction"] == row["gold"]
        rows.append(row)
    if len(rows) != 227:
        raise ValueError(f"Expected 227 binary disagreement rows; found {len(rows)}")

    attacked = [row for row in rows if row["condition_id"] != "clean"]
    aggregate = {
        "all_binary_disagreements": summarize(rows),
        "attacked_binary_disagreements": summarize(attacked),
        "by_condition": {
            condition: summarize(
                [row for row in rows if row["condition_id"] == condition]
            )
            for condition in CONDITIONS
        },
        "by_model_condition": {
            model: {
                condition: summarize(
                    [
                        row
                        for row in rows
                        if row["victim_model_id"] == model
                        and row["condition_id"] == condition
                    ]
                )
                for condition in CONDITIONS
            }
            for model in sorted({row["victim_model_id"] for row in rows})
        },
    }
    projection = {}
    for condition in CONDITIONS:
        baseline = base["projected_full_system"]["aggregate"][condition]
        group = aggregate["by_condition"][condition]
        champion_correct = baseline["systems"][
            "counter_loose_then_answerability"
        ]["correct"]
        total = baseline["rows"]
        projection[condition] = {
            "rows": total,
            "systems": {
                "champion": {
                    "correct": champion_correct,
                    "accuracy": champion_correct / total,
                },
                **{
                    variant: {
                        "correct": champion_correct
                        + group["comparisons"][f"{variant}_vs_champion"]["net"],
                        "accuracy": (
                            champion_correct
                            + group["comparisons"][f"{variant}_vs_champion"]["net"]
                        )
                        / total,
                    }
                    for variant in ("control", "full")
                },
            },
        }
    result = {
        "evaluation_schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "status": "frozen_calls_post_label_evaluation",
        "result": (
            "negative: matched deliberation and fixed-context stress arbitration both "
            "reduce accuracy relative to the selected typed corroboration method"
        ),
        "interpretation": (
            "The full selector was frozen before its outputs, but these development claims "
            "were previously opened. The stress intervention is therefore a controlled "
            "development experiment, not independent confirmation."
        ),
        "aggregate": aggregate,
        "projected_full_system": projection,
        "accounting": {
            "unique_arbiter_calls": len(cache_keys),
            "referenced_usage": read_usage(args.cache_root, cache_keys),
        },
        "private_rows": rows,
    }
    atomic_json(args.output, result)
    public = {key: value for key, value in result.items() if key != "private_rows"}
    print(json.dumps(public, indent=2))


if __name__ == "__main__":
    main()
