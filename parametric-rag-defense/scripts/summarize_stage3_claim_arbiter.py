#!/usr/bin/env python3
"""Evaluate cached Stage 3 outputs against RAG and memory-only baselines."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json

LABELS = ("Supported", "Refuted")


def candidate_prediction(candidate: dict[str, Any]) -> str | None:
    leaders = candidate["leading_verdicts"]
    return leaders[0] if len(leaders) == 1 else None


def ensemble_prediction(candidates: list[dict[str, Any]]) -> str | None:
    counts = Counter(
        prediction
        for candidate in candidates
        if (prediction := candidate_prediction(candidate)) is not None
    )
    if not counts:
        return None
    highest = max(counts.values())
    leaders = [verdict for verdict, count in counts.items() if count == highest]
    return leaders[0] if len(leaders) == 1 and highest >= 2 else None


def macro_f1(golds: list[str], predictions: list[str | None]) -> float:
    scores = []
    for label in LABELS:
        tp = sum(gold == label and prediction == label for gold, prediction in zip(golds, predictions))
        fp = sum(gold != label and prediction == label for gold, prediction in zip(golds, predictions))
        fn = sum(gold == label and prediction != label for gold, prediction in zip(golds, predictions))
        denominator = 2 * tp + fp + fn
        scores.append((2 * tp / denominator) if denominator else 0.0)
    return sum(scores) / len(scores)


def metrics(golds: list[str], predictions: list[str | None]) -> dict[str, Any]:
    correct = sum(gold == prediction for gold, prediction in zip(golds, predictions))
    return {
        "correct": correct,
        "total": len(golds),
        "accuracy": correct / len(golds) if golds else None,
        "macro_f1": macro_f1(golds, predictions) if golds else None,
        "abstaining_or_nonbinary_predictions": sum(prediction not in LABELS for prediction in predictions),
    }


def paired_outcomes(
    golds: list[str], first: list[str | None], second: list[str | None]
) -> dict[str, int]:
    result = {"both_correct": 0, "first_only_correct": 0, "second_only_correct": 0, "neither_correct": 0}
    for gold, first_prediction, second_prediction in zip(golds, first, second):
        first_correct = first_prediction == gold
        second_correct = second_prediction == gold
        if first_correct and second_correct:
            result["both_correct"] += 1
        elif first_correct:
            result["first_only_correct"] += 1
        elif second_correct:
            result["second_only_correct"] += 1
        else:
            result["neither_correct"] += 1
    return result


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    golds = [row["gold"] for row in rows]
    systems = {
        "stage3": [row["stage3"] for row in rows],
        "rag": [row["rag"] for row in rows],
        "same_model_memory": [row["same_memory"] for row in rows],
        "memory_ensemble": [row["memory_ensemble"] for row in rows],
    }
    individual_ids = sorted(
        {model_id for row in rows for model_id in row["individual_memory"]}
    )
    for model_id in individual_ids:
        systems[f"memory_{model_id}"] = [row["individual_memory"][model_id] for row in rows]
    system_metrics = {name: metrics(golds, predictions) for name, predictions in systems.items()}
    model_only_names = [name for name in system_metrics if name.startswith("memory_")]
    strongest_name = max(
        model_only_names,
        key=lambda name: (system_metrics[name]["accuracy"], system_metrics[name]["macro_f1"]),
    )
    strongest_accuracy = system_metrics[strongest_name]["accuracy"]
    stage3_predictions = systems["stage3"]
    rag_predictions = systems["rag"]
    strongest_predictions = systems[strongest_name]
    routes = Counter(row["route"] for row in rows)
    route_correct = Counter(row["route"] for row in rows if row["stage3"] == row["gold"])
    route_comparison: dict[str, dict[str, int]] = {}
    for route in sorted(routes):
        route_indices = [index for index, row in enumerate(rows) if row["route"] == route]
        route_stage3 = [stage3_predictions[index] for index in route_indices]
        route_strongest = [strongest_predictions[index] for index in route_indices]
        route_golds = [golds[index] for index in route_indices]
        route_comparison[route] = {
            "pairs": len(route_indices),
            "stage3_correct": sum(
                prediction == gold for prediction, gold in zip(route_stage3, route_golds)
            ),
            "strongest_memory_correct": sum(
                prediction == gold for prediction, gold in zip(route_strongest, route_golds)
            ),
            "stage3_only_correct": sum(
                stage3_prediction == gold and memory_prediction != gold
                for stage3_prediction, memory_prediction, gold in zip(
                    route_stage3, route_strongest, route_golds
                )
            ),
            "strongest_memory_only_correct": sum(
                stage3_prediction != gold and memory_prediction == gold
                for stage3_prediction, memory_prediction, gold in zip(
                    route_stage3, route_strongest, route_golds
                )
            ),
        }
    disagreement_rows = [row for row in rows if row["rag"] != row["memory_ensemble"]]
    result = {
        "pairs": len(rows),
        "systems": system_metrics,
        "strongest_model_only_baseline": strongest_name,
        "stage3_vs_rag_outcomes": paired_outcomes(golds, stage3_predictions, rag_predictions),
        "stage3_vs_strongest_model_only_outcomes": paired_outcomes(
            golds, stage3_predictions, strongest_predictions
        ),
        "rag_strongest_model_only_oracle_accuracy": (
            sum(
                rag_prediction == gold or memory_prediction == gold
                for gold, rag_prediction, memory_prediction in zip(
                    golds, rag_predictions, strongest_predictions
                )
            )
            / len(golds)
            if golds
            else None
        ),
        "routes": dict(sorted(routes.items())),
        "route_accuracy": {
            route: route_correct[route] / count for route, count in sorted(routes.items())
        },
        "route_comparison_to_strongest_memory": route_comparison,
        "changed_strongest_memory_prediction": sum(
            stage3_prediction != memory_prediction
            for stage3_prediction, memory_prediction in zip(
                stage3_predictions, strongest_predictions
            )
        ),
        "rag_memory_ensemble_disagreements": len(disagreement_rows),
        "stage3_accuracy_on_rag_memory_disagreements": (
            sum(row["stage3"] == row["gold"] for row in disagreement_rows) / len(disagreement_rows)
            if disagreement_rows
            else None
        ),
        "always_choose_memory_ensemble_accuracy_on_disagreements": (
            sum(row["memory_ensemble"] == row["gold"] for row in disagreement_rows)
            / len(disagreement_rows)
            if disagreement_rows
            else None
        ),
        "success_gate": {
            "stage3_minus_rag_accuracy": system_metrics["stage3"]["accuracy"]
            - system_metrics["rag"]["accuracy"],
            "stage3_minus_strongest_model_only_accuracy": system_metrics["stage3"]["accuracy"]
            - strongest_accuracy,
            "beats_rag": system_metrics["stage3"]["accuracy"] > system_metrics["rag"]["accuracy"],
            "beats_strongest_model_only": system_metrics["stage3"]["accuracy"] > strongest_accuracy,
            "beats_both": system_metrics["stage3"]["accuracy"]
            > max(system_metrics["rag"]["accuracy"], strongest_accuracy),
        },
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("artifacts/runs/stage3/stage3_claim_arbiter_v1"),
    )
    parser.add_argument(
        "--labels", type=Path, default=Path("artifacts/evaluation/stage1_labels.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/evaluation/stage3_claim_arbiter_v1.json")
    )
    args = parser.parse_args()

    manifest = json.loads((args.run_root / "private_manifest.json").read_text(encoding="utf-8"))
    if manifest["failures"]:
        raise ValueError("Stage 3 manifest contains failures; repair them before evaluation")
    labels = json.loads(args.labels.read_text(encoding="utf-8"))["development"]
    evaluation_rows: list[dict[str, Any]] = []
    for row in manifest["outputs"]:
        output = json.loads(Path(row["output_path"]).read_text(encoding="utf-8"))
        packet = json.loads(Path(row["packet_path"]).read_text(encoding="utf-8"))
        candidates = packet["visible"]["memory_only_assessments"]
        candidate_by_alias = {candidate["candidate_id"]: candidate for candidate in candidates}
        alias_by_model = {
            model_id: alias
            for alias, model_id in packet["provenance"]["internal_candidate_map"].items()
        }
        individual_memory = {
            model_id: candidate_prediction(candidate_by_alias[alias])
            for model_id, alias in alias_by_model.items()
        }
        evaluation_rows.append(
            {
                "claim_id": row["claim_id"],
                "victim_model_id": row["victim_model_id"],
                "condition_id": row["condition_id"],
                "arbiter_model_id": row["arbiter_model_id"],
                "gold": labels[str(row["claim_id"])],
                "stage3": output["arbiter"]["judgment"]["final_verdict"],
                "route": output["arbiter"]["judgment"]["route"],
                "rag": packet["visible"]["retrieval_assessment"]["verdict"],
                "same_memory": individual_memory[row["victim_model_id"]],
                "memory_ensemble": ensemble_prediction(candidates),
                "individual_memory": individual_memory,
            }
        )

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    aggregate: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in evaluation_rows:
        grouped[(row["arbiter_model_id"], row["victim_model_id"], row["condition_id"])].append(row)
        aggregate[(row["arbiter_model_id"], row["condition_id"])].append(row)
    output = {
        "summary_schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "warning": "OFFLINE EVALUATION: gold and condition metadata were joined only here",
        "aggregate_by_arbiter_and_condition": {
            arbiter: {
                condition: summarize(aggregate[(arbiter, condition)])
                for condition in sorted(
                    condition for model, condition in aggregate if model == arbiter
                )
            }
            for arbiter in sorted(model for model, _condition in aggregate)
        },
        "by_arbiter_victim_condition": {
            arbiter: {
                victim: {
                    condition: summarize(grouped[(arbiter, victim, condition)])
                    for condition in sorted(
                        condition
                        for model, grouped_victim, condition in grouped
                        if model == arbiter and grouped_victim == victim
                    )
                }
                for victim in sorted(
                    grouped_victim
                    for model, grouped_victim, _condition in grouped
                    if model == arbiter
                )
            }
            for arbiter in sorted(model for model, _victim, _condition in grouped)
        },
        "interpretation": (
            "This is method-design evidence, not held-out validation. The Stage 3 workflow/model "
            "must be frozen before opening development_validation."
        ),
    }
    atomic_json(args.output, output)
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
