#!/usr/bin/env python3
"""Evaluate the frozen tiered environment-plus-corroboration policy."""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.environment_drift import (
    count_disagreements,
    drift_alarm,
    drift_level,
    tiered_environment_prediction,
)
from summarize_evidence_signal import evidence_label

BASE_CONDITIONS = (
    "clean",
    "fact2fiction_p0.001",
    "fact2fiction_p0.0025",
    "fact2fiction_p0.005",
    "fact2fiction_p0.0075",
    "fact2fiction_p0.01",
)
HIGH_RATE_CONDITIONS = ("fact2fiction_p0.04", "fact2fiction_p0.08")
SYSTEMS = ("rag", "memory", "cascade", "loose", "strict", "tiered", "oracle")


def identity(row: dict[str, Any]) -> tuple[str, int, str]:
    return row["victim_model_id"], int(row["claim_id"]), row["condition_id"]


def endpoint_prediction(row: dict[str, Any], label: str | None) -> str:
    if label in {"Supported", "Refuted"} and sum(
        label == row[field] for field in ("rag_prediction", "memory_prediction")
    ) == 1:
        return label
    return row["cascade_prediction"]


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
            int(row[f"{left}_prediction"] == row["gold"])
            - int(row[f"{right}_prediction"] == row["gold"])
        )
    claims = sorted(by_claim)
    if not claims:
        return [0.0, 0.0]
    rng = random.Random(20260812)
    values = []
    for _ in range(5000):
        selected = rng.choices(claims, k=len(claims))
        deltas = [value for claim in selected for value in by_claim[claim]]
        values.append(sum(deltas) / len(deltas))
    values.sort()
    return [values[125], values[4874]]


def comparison(
    rows: list[dict[str, Any]], left: str, right: str
) -> dict[str, Any]:
    left_only = sum(
        row[f"{left}_prediction"] == row["gold"]
        and row[f"{right}_prediction"] != row["gold"]
        for row in rows
    )
    right_only = sum(
        row[f"{left}_prediction"] != row["gold"]
        and row[f"{right}_prediction"] == row["gold"]
        for row in rows
    )
    return {
        "left_only_correct": left_only,
        "right_only_correct": right_only,
        "net": left_only - right_only,
        "exact_p": exact_paired_pvalue(left_only, right_only),
        "claim_cluster_bootstrap95_accuracy_delta": bootstrap_delta(
            rows, left, right
        ),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "drift_levels": sorted({row["drift_level"] for row in rows}),
        "systems": {
            system: {
                "correct": sum(
                    row[f"{system}_prediction"] == row["gold"] for row in rows
                ),
                "accuracy": (
                    sum(row[f"{system}_prediction"] == row["gold"] for row in rows)
                    / len(rows)
                    if rows
                    else None
                ),
            }
            for system in SYSTEMS
        },
        "comparisons": {
            f"tiered_vs_{baseline}": comparison(rows, "tiered", baseline)
            for baseline in ("rag", "memory", "cascade", "loose", "strict")
        },
    }


def load_new_counter_labels(
    run_root: Path,
) -> dict[tuple[str, int, str], tuple[str | None, str | None]]:
    audit = json.loads((run_root / "audit.json").read_text())
    if audit.get("status") != "passed" or audit.get("phase") != "mapped":
        raise ValueError("New counter extension must pass its mapped audit")
    manifest = json.loads((run_root / "private_manifest.json").read_text())
    expected_outputs = len(manifest.get("rows", []))
    if (
        manifest.get("failures")
        or not expected_outputs
        or manifest.get("completed_outputs") != expected_outputs
    ):
        raise ValueError("New counter extension is incomplete")
    result = {}
    for descriptor in manifest["rows"]:
        judgment = json.loads(Path(descriptor["output_path"]).read_text())[
            "judgment"
        ]
        result[identity(descriptor)] = (
            evidence_label(judgment),
            evidence_label(judgment, strict=True),
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("configs/environment_drift_gate_v1.json"),
    )
    parser.add_argument(
        "--amendment",
        type=Path,
        default=Path("configs/environment_drift_gate_v1_amendment_1.json"),
    )
    parser.add_argument(
        "--answerability",
        type=Path,
        default=Path("artifacts/evaluation/answerability_cascade_v1.json"),
    )
    parser.add_argument(
        "--old-counter",
        type=Path,
        default=Path("artifacts/evaluation/counter_retrieval_signal_v2.json"),
    )
    parser.add_argument(
        "--new-counter-root",
        type=Path,
        default=Path(
            "artifacts/runs/counter_retrieval/counter_retrieval_rate075_1pct_v1"
        ),
    )
    parser.add_argument(
        "--high-counter-root",
        type=Path,
        help="Optional frozen 4/8-percent counter-retrieval extension.",
    )
    parser.add_argument(
        "--high-amendment",
        type=Path,
        default=Path("configs/environment_drift_gate_v1_amendment_2.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluation/tiered_environment_policy_v1.json"),
    )
    args = parser.parse_args()

    protocol = json.loads(args.protocol.read_text())
    amendment = json.loads(args.amendment.read_text())
    if protocol.get("status") != "frozen_before_environment_gate_evaluation":
        raise ValueError("Base environment protocol is not frozen")
    if amendment.get("status") != "frozen_before_0.75_and_1_percent_counter_corroboration_calls":
        raise ValueError("Tiered amendment is not frozen")
    conditions = BASE_CONDITIONS
    if args.high_counter_root is not None:
        high_amendment = json.loads(args.high_amendment.read_text())
        if high_amendment.get("status") != "frozen_before_4_and_8_percent_counter_corroboration_calls":
            raise ValueError("High-rate amendment is not frozen")
        conditions += HIGH_RATE_CONDITIONS
    answerability = json.loads(args.answerability.read_text())
    all_rows = [
        dict(row)
        for row in answerability["private_rows"]
        if row["condition_id"] in conditions
    ]
    old_counter = json.loads(args.old_counter.read_text())
    counter_labels = {
        identity(row): (row["counter_loose_label"], row["counter_strict_label"])
        for row in old_counter["private_rows"]
    }
    new_labels = load_new_counter_labels(args.new_counter_root)
    overlap = set(counter_labels) & set(new_labels)
    if overlap:
        raise ValueError(f"Old/new counter scopes overlap: {len(overlap)}")
    counter_labels.update(new_labels)
    if args.high_counter_root is not None:
        high_labels = load_new_counter_labels(args.high_counter_root)
        overlap = set(counter_labels) & set(high_labels)
        if overlap:
            raise ValueError(f"Prior/high counter scopes overlap: {len(overlap)}")
        counter_labels.update(high_labels)

    models = sorted({row["victim_model_id"] for row in all_rows})
    reference = {}
    for model in models:
        scoped = [
            row
            for row in all_rows
            if row["victim_model_id"] == model and row["condition_id"] == "clean"
        ]
        disagreements, eligible = count_disagreements(scoped)
        reference[model] = {
            "clean_disagreements": disagreements,
            "clean_eligible": eligible,
        }

    cell_drift = {}
    for model in models:
        cell_drift[model] = {}
        for condition in conditions:
            scoped = [
                row
                for row in all_rows
                if row["victim_model_id"] == model
                and row["condition_id"] == condition
            ]
            signal = drift_alarm(
                scoped,
                **reference[model],
                significance=float(protocol["alarm"]["significance"]),
                minimum_eligible=int(protocol["alarm"]["minimum_answerable_claims"]),
            )
            signal["drift_level"] = (
                drift_level(signal["posterior_predictive_upper_tail"])
                if signal["eligible"]
                >= int(protocol["alarm"]["minimum_answerable_claims"])
                else "normal"
            )
            cell_drift[model][condition] = signal

    rows = []
    for row in all_rows:
        row_id = identity(row)
        disagrees = row["rag_prediction"] != row["memory_prediction"]
        if disagrees and row_id not in counter_labels:
            raise ValueError(f"Missing counter evidence for disagreement: {row_id}")
        loose_label, strict_label = counter_labels.get(row_id, (None, None))
        row["loose_prediction"] = endpoint_prediction(row, loose_label)
        row["strict_prediction"] = endpoint_prediction(row, strict_label)
        row["champion_prediction"] = row["loose_prediction"]
        row["strict_champion_prediction"] = row["strict_prediction"]
        row["drift_level"] = cell_drift[row["victim_model_id"]][
            row["condition_id"]
        ]["drift_level"]
        row["tiered_prediction"] = tiered_environment_prediction(
            row, level=row["drift_level"]
        )
        row["oracle_prediction"] = (
            row["rag_prediction"]
            if row["rag_prediction"] == row["gold"]
            else row["memory_prediction"]
        )
        rows.append(row)

    aggregate = {
        condition: summarize(
            [row for row in rows if row["condition_id"] == condition]
        )
        for condition in conditions
    }
    by_model_condition = {
        model: {
            condition: summarize(
                [
                    row
                    for row in rows
                    if row["victim_model_id"] == model
                    and row["condition_id"] == condition
                ]
            )
            for condition in conditions
        }
        for model in models
    }
    result = {
        "evaluation_schema_version": 1,
        "experiment_id": "tiered_environment_policy_v1",
        "status": "post_freeze_rate_extension_development_evaluation",
        "warning": (
            "The tier thresholds and each rate-extension scope were frozen before their new "
            "counter reports, but the hypothesis and tier refinement used prior development "
            "labels. This is not independent confirmation."
        ),
        "policy": {
            "normal": "loose directional counter corroboration over answerability",
            "warning": "unopposed direct counter corroboration over answerability",
            "critical": "answerability fallback with no retrieval-based override",
            "forbidden_inputs": [
                "condition or nominal attack rate",
                "attacker identity",
                "poison provenance or exposure",
                "model identity as a learned feature",
                "gold or correctness",
            ],
        },
        "cell_drift": cell_drift,
        "aggregate": aggregate,
        "by_model_condition": by_model_condition,
        "private_rows": rows,
    }
    atomic_json(args.output, result)
    print(json.dumps({key: value for key, value in result.items() if key != "private_rows"}, indent=2))


if __name__ == "__main__":
    main()
