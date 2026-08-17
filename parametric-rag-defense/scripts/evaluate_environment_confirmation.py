#!/usr/bin/env python3
"""Evaluate the frozen environment-conditioned policy on fresh confirmation rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.environment_drift import drift_alarm, drift_level
from summarize_evidence_signal import evidence_label

SYSTEMS = ("rag", "memory", "answerability", "loose", "strict", "proposed", "oracle")


def identity(row: dict[str, Any]) -> tuple[str, int, str]:
    return row["victim_model_id"], int(row["claim_id"]), row["condition_id"]


def endpoint_prediction(row: dict[str, Any], label: str | None) -> str:
    if label in {"Supported", "Refuted"} and sum(
        label == row[key] for key in ("rag_prediction", "memory_prediction")
    ) == 1:
        return label
    return row["answerability_prediction"]


def exact_paired_pvalue(left_only: int, right_only: int) -> float:
    discordant = left_only + right_only
    if not discordant:
        return 1.0
    tail = sum(
        math.comb(discordant, value)
        for value in range(min(left_only, right_only) + 1)
    )
    return min(1.0, 2.0 * tail / (2**discordant))


def bootstrap_delta(rows: list[dict[str, Any]], left: str, right: str) -> list[float]:
    by_claim: dict[int, list[int]] = {}
    for row in rows:
        by_claim.setdefault(int(row["claim_id"]), []).append(
            int(row[f"{left}_prediction"] == row["gold"])
            - int(row[f"{right}_prediction"] == row["gold"])
        )
    if not by_claim:
        return [0.0, 0.0]
    claims = sorted(by_claim)
    rng = random.Random(20260812)
    values = []
    for _ in range(5000):
        selected = rng.choices(claims, k=len(claims))
        deltas = [delta for claim in selected for delta in by_claim[claim]]
        values.append(sum(deltas) / len(deltas))
    values.sort()
    return [values[125], values[4874]]


def comparison(rows: list[dict[str, Any]], left: str, right: str) -> dict[str, Any]:
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
        "claim_cluster_bootstrap95_accuracy_delta": bootstrap_delta(rows, left, right),
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
            f"proposed_vs_{baseline}": comparison(rows, "proposed", baseline)
            for baseline in ("rag", "memory", "answerability", "loose", "strict")
        },
    }


def load_counter_labels(run_root: Path) -> dict[tuple[str, int, str], tuple[str | None, str | None]]:
    audit = json.loads((run_root / "audit.json").read_text(encoding="utf-8"))
    if audit.get("status") != "passed" or audit.get("phase") != "mapped":
        raise ValueError("counter-retrieval run must pass its mapped audit")
    manifest = json.loads((run_root / "private_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("failures") or manifest.get("completed_outputs") != len(
        manifest.get("rows", [])
    ):
        raise ValueError("counter-retrieval run is incomplete")
    result = {}
    for row in manifest["rows"]:
        judgment = json.loads(Path(row["output_path"]).read_text(encoding="utf-8"))[
            "judgment"
        ]
        result[identity(row)] = (
            evidence_label(judgment),
            evidence_label(judgment, strict=True),
        )
    return result


def deterministic_order_key(row: dict[str, Any], experiment_id: str) -> str:
    return hashlib.sha256(
        (
            f"{experiment_id}|{row['victim_model_id']}|"
            f"{row['condition_id']}|{row['claim_id']}"
        ).encode("utf-8")
    ).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("configs/environment_confirmation_protocol_v1.json"),
    )
    parser.add_argument(
        "--endpoints",
        type=Path,
        default=Path(
            "artifacts/evaluation/environment_confirmation_train_v1/endpoint_summary.json"
        ),
    )
    parser.add_argument(
        "--counter-root",
        type=Path,
        default=Path(
            "artifacts/runs/environment_confirmation_train_v1/counter_retrieval/"
            "environment_confirmation_counter_v1"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "artifacts/evaluation/environment_confirmation_train_v1/"
            "environment_conditioned_results.json"
        ),
    )
    args = parser.parse_args()

    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    if protocol.get("status") != "frozen_before_fresh_confirmation_inference":
        raise ValueError("confirmation protocol was not frozen before inference")
    endpoint_result = json.loads(args.endpoints.read_text(encoding="utf-8"))
    rows = [dict(value) for value in endpoint_result["private_rows"]]
    counter_labels = load_counter_labels(args.counter_root)
    reference = protocol["selected_policy"]["fixed_clean_reference"]
    minimum = int(protocol["selected_policy"]["minimum_answerable_observations"])
    models = sorted({row["victim_model_id"] for row in rows})
    conditions = list(endpoint_result["conditions"])

    cell_drift: dict[str, dict[str, Any]] = {}
    for model in models:
        cell_drift[model] = {}
        for condition in conditions:
            scoped = [
                row
                for row in rows
                if row["victim_model_id"] == model
                and row["condition_id"] == condition
            ]
            signal = drift_alarm(
                scoped,
                clean_disagreements=int(reference[model]["disagreements"]),
                clean_eligible=int(reference[model]["answerable"]),
                significance=0.01,
                minimum_eligible=minimum,
            )
            signal["drift_level"] = (
                drift_level(signal["posterior_predictive_upper_tail"])
                if signal["eligible"] >= minimum
                else "normal"
            )
            cell_drift[model][condition] = signal

    for row in rows:
        row_id = identity(row)
        disagrees = row["rag_prediction"] != row["memory_prediction"]
        if disagrees and row_id not in counter_labels:
            raise ValueError(f"missing counter report for endpoint disagreement {row_id}")
        loose_label, strict_label = counter_labels.get(row_id, (None, None))
        row["loose_prediction"] = endpoint_prediction(row, loose_label)
        row["strict_prediction"] = endpoint_prediction(row, strict_label)
        row["drift_level"] = cell_drift[row["victim_model_id"]][
            row["condition_id"]
        ]["drift_level"]
        row["proposed_prediction"] = {
            "normal": row["loose_prediction"],
            "warning": row["strict_prediction"],
            "critical": row["answerability_prediction"],
        }[row["drift_level"]]

    attacked = [row for row in rows if row["condition_id"] != "clean"]
    aggregate = {
        condition: summarize(
            [row for row in rows if row["condition_id"] == condition]
        )
        for condition in conditions
    }
    attacked_pooled = summarize(attacked)
    attacked_by_model = {
        model: summarize(
            [row for row in attacked if row["victim_model_id"] == model]
        )
        for model in models
    }
    clean_rows = [row for row in rows if row["condition_id"] == "clean"]
    proposed_attacked = attacked_pooled["systems"]["proposed"]["accuracy"]
    pooled_raw = max(
        attacked_pooled["systems"]["rag"]["accuracy"],
        attacked_pooled["systems"]["memory"]["accuracy"],
    )
    model_wins = [
        model
        for model, value in attacked_by_model.items()
        if value["systems"]["proposed"]["accuracy"]
        > max(
            value["systems"]["rag"]["accuracy"],
            value["systems"]["memory"]["accuracy"],
        )
    ]
    clean_summary = summarize(clean_rows)
    clean_raw = max(
        clean_summary["systems"]["rag"]["accuracy"],
        clean_summary["systems"]["memory"]["accuracy"],
    )
    gates = {
        "attacked_pooled_strictly_above_both_raw": proposed_attacked > pooled_raw,
        "at_least_one_model_strictly_above_both_raw": bool(model_wins),
        "models_with_strict_pooled_win": model_wins,
        "clean_within_0.02_of_stronger_raw": (
            clean_summary["systems"]["proposed"]["accuracy"] >= clean_raw - 0.02
        ),
    }
    gates["primary_gate_passed"] = all(
        gates[key]
        for key in (
            "attacked_pooled_strictly_above_both_raw",
            "at_least_one_model_strictly_above_both_raw",
            "clean_within_0.02_of_stronger_raw",
        )
    )

    online = {}
    for model in models:
        online[model] = {}
        for condition in conditions:
            scoped = sorted(
                (
                    row
                    for row in rows
                    if row["victim_model_id"] == model
                    and row["condition_id"] == condition
                ),
                key=lambda row: deterministic_order_key(
                    row, protocol["experiment_id"]
                ),
            )
            prior_rows: list[dict[str, Any]] = []
            states = []
            answerable_seen = 0
            for index, row in enumerate(scoped, 1):
                prior_signal = drift_alarm(
                    prior_rows,
                    clean_disagreements=int(reference[model]["disagreements"]),
                    clean_eligible=int(reference[model]["answerable"]),
                    significance=0.01,
                    minimum_eligible=minimum,
                )
                level = (
                    drift_level(prior_signal["posterior_predictive_upper_tail"])
                    if prior_signal["eligible"] >= minimum
                    else "normal"
                )
                row["online_drift_level"] = level
                row["online_prediction"] = {
                    "normal": row["loose_prediction"],
                    "warning": row["strict_prediction"],
                    "critical": row["answerability_prediction"],
                }[level]
                prior_rows.append(row)
                if row["memory_answerable"]:
                    answerable_seen += 1
                    if answerable_seen in {10, 20, 40}:
                        current = drift_alarm(
                            prior_rows,
                            clean_disagreements=int(reference[model]["disagreements"]),
                            clean_eligible=int(reference[model]["answerable"]),
                            significance=0.01,
                            minimum_eligible=minimum,
                        )
                        states.append(
                            {
                                "after_answerable": answerable_seen,
                                "processed_rows": index,
                                "drift_level": (
                                    drift_level(
                                        current["posterior_predictive_upper_tail"]
                                    )
                                    if current["eligible"] >= minimum
                                    else "normal"
                                ),
                                **current,
                            }
                        )
            final = drift_alarm(
                prior_rows,
                clean_disagreements=int(reference[model]["disagreements"]),
                clean_eligible=int(reference[model]["answerable"]),
                significance=0.01,
                minimum_eligible=minimum,
            )
            states.append(
                {
                    "after_answerable": final["eligible"],
                    "processed_rows": len(scoped),
                    "checkpoint": "all",
                    "drift_level": (
                        drift_level(final["posterior_predictive_upper_tail"])
                        if final["eligible"] >= minimum
                        else "normal"
                    ),
                    **final,
                }
            )
            online[model][condition] = {
                "states": states,
                "correct": sum(row["online_prediction"] == row["gold"] for row in scoped),
                "accuracy": (
                    sum(row["online_prediction"] == row["gold"] for row in scoped)
                    / len(scoped)
                    if scoped
                    else None
                ),
            }

    result = {
        "evaluation_schema_version": 1,
        "experiment_id": protocol["experiment_id"],
        "status": "fresh_confirmation_evaluated_without_retuning",
        "policy": protocol["selected_policy"],
        "primary_gate": gates,
        "cell_drift": cell_drift,
        "aggregate": aggregate,
        "attacked_pooled": attacked_pooled,
        "attacked_by_model": attacked_by_model,
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
                for condition in conditions
            }
            for model in models
        },
        "online_prequential": online,
        "private_rows": rows,
    }
    atomic_json(args.output, result)
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "private_rows"},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
