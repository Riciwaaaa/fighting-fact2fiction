#!/usr/bin/env python3
"""Evaluate the frozen model-specific retrieval-environment drift gate."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.environment_drift import (
    drift_alarm,
    environment_prediction,
)

ROUTING_CONDITIONS = (
    "clean",
    "fact2fiction_p0.001",
    "fact2fiction_p0.0025",
    "fact2fiction_p0.005",
)


def identity(row: dict[str, Any]) -> tuple[str, int, str]:
    return row["victim_model_id"], int(row["claim_id"]), row["condition_id"]


def selected_champion(row: dict[str, Any]) -> str:
    direction = row.get("counter_loose_label")
    if direction in {"Supported", "Refuted"} and sum(
        direction == row[field] for field in ("rag_prediction", "memory_prediction")
    ) == 1:
        return direction
    return row["cascade_prediction"]


def load_development_rows(
    answerability_path: Path, counter_path: Path
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    answerability = json.loads(answerability_path.read_text())
    counter = json.loads(counter_path.read_text())
    counter_by_id = {identity(row): row for row in counter["private_rows"]}
    rows = []
    for source in answerability["private_rows"]:
        row = dict(source)
        counter_row = counter_by_id.get(identity(row))
        if counter_row is not None:
            row["counter_loose_label"] = counter_row["counter_loose_label"]
        row["champion_prediction"] = selected_champion(row)
        rows.append(row)
    return rows, tuple(answerability["conditions"])


def clean_reference(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    from parametric_rag_defense.environment_drift import count_disagreements

    result = {}
    for model in sorted({row["victim_model_id"] for row in rows}):
        selected = [
            row
            for row in rows
            if row["victim_model_id"] == model and row["condition_id"] == "clean"
        ]
        disagreements, eligible = count_disagreements(selected)
        result[model] = {
            "clean_disagreements": disagreements,
            "clean_eligible": eligible,
            "clean_total_rows": len(selected),
        }
    return result


def alarm_for(
    rows: list[dict[str, Any]],
    reference: dict[str, int],
    *,
    significance: float,
    minimum_eligible: int,
) -> dict[str, Any]:
    return drift_alarm(
        rows,
        clean_disagreements=reference["clean_disagreements"],
        clean_eligible=reference["clean_eligible"],
        significance=significance,
        minimum_eligible=minimum_eligible,
    )


def routing_summary(rows: list[dict[str, Any]], *, alarm: bool) -> dict[str, Any]:
    systems = ("rag", "memory", "cascade", "champion")
    result = {
        "rows": len(rows),
        "alarm": alarm,
        "selected_mode": "answerability_fallback" if alarm else "corroboration_blend",
        "systems": {
            system: {
                "correct": sum(row[f"{system}_prediction"] == row["gold"] for row in rows),
                "accuracy": (
                    sum(row[f"{system}_prediction"] == row["gold"] for row in rows)
                    / len(rows)
                    if rows
                    else None
                ),
            }
            for system in systems
        },
    }
    predictions = [environment_prediction(row, alarm=alarm) for row in rows]
    correct = sum(
        prediction == row["gold"] for prediction, row in zip(predictions, rows)
    )
    result["systems"]["environment_gate"] = {
        "correct": correct,
        "accuracy": correct / len(rows) if rows else None,
    }
    result["changes_from_champion"] = sum(
        prediction != row["champion_prediction"]
        for prediction, row in zip(predictions, rows)
    )
    return result


def load_locked_rows(manifest_path: Path) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("failures") or len(manifest["outputs"]) != manifest["expected"]:
        raise ValueError("Locked input manifest is incomplete")
    rows = []
    for descriptor in manifest["outputs"]:
        visible = json.loads(Path(descriptor["aligned_packet_path"]).read_text())[
            "visible"
        ]
        memory = visible["memory_only_assessment"]
        if len(memory["leading_verdicts"]) != 1:
            raise ValueError("Locked memory record has a non-unique leading verdict")
        memory_prediction = memory["leading_verdicts"][0]
        rows.append(
            {
                "victim_model_id": descriptor["victim_model_id"],
                "claim_id": int(descriptor["claim_id"]),
                "condition_id": descriptor["condition_id"],
                "attacker_model_id": descriptor["attacker_model_id"],
                "memory_prediction": memory_prediction,
                "memory_answerable": memory_prediction in {"Supported", "Refuted"},
                "rag_prediction": visible["retrieval_assessment"]["verdict"],
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol", type=Path, default=Path("configs/environment_drift_gate_v1.json")
    )
    parser.add_argument(
        "--answerability",
        type=Path,
        default=Path("artifacts/evaluation/answerability_cascade_v1.json"),
    )
    parser.add_argument(
        "--counter",
        type=Path,
        default=Path("artifacts/evaluation/counter_retrieval_signal_v2.json"),
    )
    parser.add_argument(
        "--locked-manifest",
        type=Path,
        default=Path(
            "artifacts/runs/stage3/stage3_locked_neutral_inputs_v1/private_manifest.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluation/environment_drift_gate_v1.json"),
    )
    args = parser.parse_args()

    protocol = json.loads(args.protocol.read_text())
    if protocol.get("status") != "frozen_before_environment_gate_evaluation":
        raise ValueError("Environment gate protocol is not frozen")
    significance = float(protocol["alarm"]["significance"])
    minimum = int(protocol["alarm"]["minimum_answerable_claims"])
    development, conditions = load_development_rows(args.answerability, args.counter)
    reference = clean_reference(development)
    models = sorted(reference)

    development_detection = {}
    for model in models:
        development_detection[model] = {}
        for condition in conditions:
            scoped = [
                row
                for row in development
                if row["victim_model_id"] == model
                and row["condition_id"] == condition
            ]
            development_detection[model][condition] = alarm_for(
                scoped,
                reference[model],
                significance=significance,
                minimum_eligible=minimum,
            )

    routing_by_model_condition = {}
    for model in models:
        routing_by_model_condition[model] = {}
        for condition in ROUTING_CONDITIONS:
            scoped = [
                row
                for row in development
                if row["victim_model_id"] == model
                and row["condition_id"] == condition
            ]
            alarm = development_detection[model][condition]["alarm"]
            routing_by_model_condition[model][condition] = routing_summary(
                scoped, alarm=alarm
            )
    routing_aggregate = {}
    for condition in ROUTING_CONDITIONS:
        cells = [routing_by_model_condition[model][condition] for model in models]
        systems = cells[0]["systems"]
        total = sum(cell["rows"] for cell in cells)
        routing_aggregate[condition] = {
            "rows": total,
            "alarmed_models": [
                model
                for model in models
                if routing_by_model_condition[model][condition]["alarm"]
            ],
            "systems": {
                system: {
                    "correct": sum(
                        routing_by_model_condition[model][condition]["systems"][system][
                            "correct"
                        ]
                        for model in models
                    ),
                    "accuracy": sum(
                        routing_by_model_condition[model][condition]["systems"][system][
                            "correct"
                        ]
                        for model in models
                    )
                    / total,
                }
                for system in systems
            },
        }

    locked = load_locked_rows(args.locked_manifest)
    locked_detection = {}
    for model in models:
        cells = sorted(
            {
                (row["condition_id"], row["attacker_model_id"])
                for row in locked
                if row["victim_model_id"] == model
            },
            key=lambda item: (item[0], item[1] or ""),
        )
        locked_detection[model] = {}
        for condition, attacker in cells:
            scoped = [
                row
                for row in locked
                if row["victim_model_id"] == model
                and row["condition_id"] == condition
                and row["attacker_model_id"] == attacker
            ]
            label = "clean" if attacker is None else f"attacker_{attacker}"
            locked_detection[model][label] = {
                **alarm_for(
                    scoped,
                    reference[model],
                    significance=significance,
                    minimum_eligible=minimum,
                ),
                "condition_id_private_reporting_only": condition,
                "attacker_model_id_private_reporting_only": attacker,
            }

    result = {
        "evaluation_schema_version": 1,
        "experiment_id": protocol["experiment_id"],
        "status": "post_freeze_development_and_cross_claim_transfer_evaluation",
        "warning": (
            "The detector was frozen before this script joined condition/cell outcomes, but "
            "the development rate curve motivated the hypothesis and the locked claims were "
            "opened by earlier work. Neither result is independent confirmation."
        ),
        "method": {
            "significance": significance,
            "minimum_answerable_claims": minimum,
            "clean_reference": reference,
            "alarm_inputs": (
                "Only same-model binary-memory answerability and RAG-memory disagreement; "
                "no rate, attacker, provenance, exposure, model identity, or gold."
            ),
        },
        "development_detection": development_detection,
        "development_routing": {
            "scope": (
                "Only clean through 0.5%, where the selected corroboration outputs exist."
            ),
            "aggregate": routing_aggregate,
            "by_model_condition": routing_by_model_condition,
        },
        "locked_cross_claim_detection": locked_detection,
        "alarm_counts": {
            "development_by_condition": {
                condition: sum(
                    development_detection[model][condition]["alarm"] for model in models
                )
                for condition in conditions
            },
            "locked_clean": sum(
                locked_detection[model]["clean"]["alarm"] for model in models
            ),
            "locked_attacked_cells": Counter(
                str(cell["alarm"])
                for model in models
                for label, cell in locked_detection[model].items()
                if label != "clean"
            ),
        },
    }
    result["alarm_counts"]["locked_attacked_cells"] = dict(
        result["alarm_counts"]["locked_attacked_cells"]
    )
    atomic_json(args.output, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
