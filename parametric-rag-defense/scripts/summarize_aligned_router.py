#!/usr/bin/env python3
"""Offline per-model evaluation of exact same-model router A/B outputs."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from parametric_rag_defense.aligned_workflow import candidate_prediction
from parametric_rag_defense.averitec import atomic_json

LABELS = ("Supported", "Refuted")


def metrics(golds: list[str], predictions: list[str | None]) -> dict[str, Any]:
    correct = sum(gold == prediction for gold, prediction in zip(golds, predictions))
    f1s = []
    for label in LABELS:
        tp = sum(gold == label and prediction == label for gold, prediction in zip(golds, predictions))
        fp = sum(gold != label and prediction == label for gold, prediction in zip(golds, predictions))
        fn = sum(gold == label and prediction != label for gold, prediction in zip(golds, predictions))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return {
        "total": len(golds),
        "correct": correct,
        "accuracy": correct / len(golds) if golds else None,
        "macro_f1": sum(f1s) / len(f1s) if f1s else None,
        "abstaining_or_nonbinary": sum(prediction not in LABELS for prediction in predictions),
    }


def paired(golds: list[str], first: list[str | None], second: list[str | None]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for gold, first_prediction, second_prediction in zip(golds, first, second):
        first_correct = first_prediction == gold
        second_correct = second_prediction == gold
        if first_correct and second_correct:
            counts["both_correct"] += 1
        elif first_correct:
            counts["first_only_correct"] += 1
        elif second_correct:
            counts["second_only_correct"] += 1
        else:
            counts["neither_correct"] += 1
    result = {key: counts[key] for key in ("both_correct", "first_only_correct", "second_only_correct", "neither_correct")}
    discordant = result["first_only_correct"] + result["second_only_correct"]
    if discordant:
        tail = sum(
            math.comb(discordant, index) * (0.5**discordant)
            for index in range(min(result["first_only_correct"], result["second_only_correct"]) + 1)
        )
        result["two_sided_exact_mcnemar_p"] = min(1.0, 2 * tail)
    else:
        result["two_sided_exact_mcnemar_p"] = 1.0
    return result


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    golds = [row["gold"] for row in rows]
    rag = [row["rag"] for row in rows]
    memory = [row["memory"] for row in rows]
    router = [row["router"] for row in rows]
    endpoint_outcomes = paired(golds, rag, memory)
    disagreement_rows = [row for row in rows if row["rag"] != row["memory"]]
    routes = Counter(row["route"] for row in rows)
    route_metrics = {}
    for route in sorted(routes):
        group = [row for row in rows if row["route"] == route]
        route_metrics[route] = metrics(
            [row["gold"] for row in group], [row["router"] for row in group]
        )
    router_vs_memory = paired(golds, router, memory)
    return {
        "pairs": len(rows),
        "systems": {
            "rag": metrics(golds, rag),
            "same_model_memory": metrics(golds, memory),
            "router": metrics(golds, router),
        },
        "endpoint_outcomes": endpoint_outcomes,
        "endpoint_oracle_correct": len(rows) - endpoint_outcomes["neither_correct"],
        "endpoint_oracle_accuracy": (
            (len(rows) - endpoint_outcomes["neither_correct"]) / len(rows) if rows else None
        ),
        "endpoint_disagreements": len(disagreement_rows),
        "router_accuracy_on_disagreements": (
            sum(row["router"] == row["gold"] for row in disagreement_rows) / len(disagreement_rows)
            if disagreement_rows
            else None
        ),
        "routes": dict(sorted(routes.items())),
        "route_metrics": route_metrics,
        "router_vs_memory": router_vs_memory,
        "router_vs_rag": paired(golds, router, rag),
        "memory_to_router_changes": sum(row["router"] != row["memory"] for row in rows),
        "retrieval_only_cases_recovered": sum(
            row["rag"] == row["gold"] and row["memory"] != row["gold"] and row["router"] == row["gold"]
            for row in rows
        ),
        "memory_only_cases_sacrificed": sum(
            row["memory"] == row["gold"] and row["rag"] != row["gold"] and row["router"] != row["gold"]
            for row in rows
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root", type=Path, default=Path("artifacts/runs/stage3/stage3_same_model_ab_v1")
    )
    parser.add_argument("--labels", type=Path, default=Path("artifacts/evaluation/stage1_labels.json"))
    parser.add_argument(
        "--stage2-summary", type=Path, default=Path("artifacts/evaluation/stage2_signal_v1.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/evaluation/stage3_same_model_ab_v1.json")
    )
    args = parser.parse_args()
    manifest = json.loads((args.run_root / "private_manifest.json").read_text(encoding="utf-8"))
    if manifest["dry_run"] or manifest["failures"]:
        raise ValueError("Aligned router manifest is dry-run or contains failures")
    labels = json.loads(args.labels.read_text(encoding="utf-8"))["development"]
    evaluation_rows = []
    for row in manifest["outputs"]:
        packet = json.loads(Path(row["aligned_packet_path"]).read_text(encoding="utf-8"))
        output = json.loads(Path(row["output_path"]).read_text(encoding="utf-8"))
        if packet["provenance"]["same_model_id"] != row["victim_model_id"]:
            raise ValueError("same-model packet provenance mismatch")
        memory = candidate_prediction(packet["visible"]["memory_only_assessment"])
        evaluation_rows.append(
            {
                "claim_id": row["claim_id"],
                "model_id": row["victim_model_id"],
                "condition_id": row["condition_id"],
                "variant": row["variant"],
                "gold": labels[str(row["claim_id"])],
                "rag": packet["visible"]["retrieval_assessment"]["verdict"],
                "memory": memory,
                "router": output["derived_prediction"],
                "route": output["router"]["judgment"]["route"],
            }
        )
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in evaluation_rows:
        grouped[(row["model_id"], row["variant"], row["condition_id"])].append(row)
    result: dict[str, Any] = {
        "evaluation_schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "warning": "OFFLINE METHOD-DESIGN EVALUATION; gold was joined only here",
        "by_model_variant_condition": {},
    }
    for model in sorted({key[0] for key in grouped}):
        result["by_model_variant_condition"][model] = {}
        for variant in sorted({key[1] for key in grouped if key[0] == model}):
            conditions = {
                condition: summarize(grouped[(model, variant, condition)])
                for condition in sorted(key[2] for key in grouped if key[:2] == (model, variant))
            }
            clean = conditions.get("clean")
            attacked = conditions.get("fact2fiction_p0.01")
            success_gate = None
            if clean and attacked:
                attacked_router = attacked["systems"]["router"]["accuracy"]
                attacked_best = max(
                    attacked["systems"]["rag"]["accuracy"],
                    attacked["systems"]["same_model_memory"]["accuracy"],
                )
                clean_router = clean["systems"]["router"]["accuracy"]
                clean_best = max(
                    clean["systems"]["rag"]["accuracy"],
                    clean["systems"]["same_model_memory"]["accuracy"],
                )
                success_gate = {
                    "beats_both_at_1pct": attacked_router > attacked_best,
                    "attacked_delta_from_best": attacked_router - attacked_best,
                    "clean_delta_from_best": clean_router - clean_best,
                    "clean_loss_within_2_points": clean_router >= clean_best - 0.02,
                    "passes": attacked_router > attacked_best and clean_router >= clean_best - 0.02,
                }
            result["by_model_variant_condition"][model][variant] = {
                "conditions": conditions,
                "success_gate": success_gate,
            }

    stage2 = json.loads(args.stage2_summary.read_text(encoding="utf-8"))
    headroom = {}
    for model, conditions in stage2["by_victim_and_condition"].items():
        headroom[model] = {}
        for condition, value in conditions.items():
            oracle_correct = value["rag_correct"] + value["same_memory_disagreement_correct"]
            best_correct = max(value["rag_correct"], value["same_memory_correct"])
            headroom[model][condition] = {
                "pairs": value["pairs"],
                "rag_accuracy": value["rag_accuracy"],
                "same_model_memory_accuracy": value["same_memory_accuracy"],
                "endpoint_oracle_accuracy": oracle_correct / value["pairs"],
                "recoverable_cases_above_best_endpoint": oracle_correct - best_correct,
                "recoverable_accuracy_points": (oracle_correct - best_correct) / value["pairs"],
            }
    result["same_model_headroom_all_cached_conditions"] = headroom
    atomic_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
