#!/usr/bin/env python3
"""Offline per-model evaluation of the targeted same-model Stage C workflow."""

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


def metrics(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    predictions = [row[field] for row in rows]
    correct = sum(prediction == row["gold"] for prediction, row in zip(predictions, rows))
    f1s = []
    for label in LABELS:
        tp = sum(row["gold"] == label and row[field] == label for row in rows)
        fp = sum(row["gold"] != label and row[field] == label for row in rows)
        fn = sum(row["gold"] == label and row[field] != label for row in rows)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return {
        "total": len(rows),
        "correct": correct,
        "accuracy": correct / len(rows) if rows else None,
        "macro_f1": sum(f1s) / len(f1s) if f1s else None,
        "abstaining_or_nonbinary": sum(prediction not in LABELS for prediction in predictions),
    }


def paired(rows: list[dict[str, Any]], first: str, second: str) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for row in rows:
        first_correct = row[first] == row["gold"]
        second_correct = row[second] == row["gold"]
        key = (
            "both_correct"
            if first_correct and second_correct
            else "first_only_correct"
            if first_correct
            else "second_only_correct"
            if second_correct
            else "neither_correct"
        )
        counts[key] += 1
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
    disagreements = [row for row in rows if row["rag"] != row["memory"]]
    proposition_bases = Counter(
        row["proposition_basis"] for row in disagreements if row["proposition_basis"] is not None
    )
    proposition_verdicts = Counter(
        row["proposition_verdict"] for row in disagreements if row["proposition_verdict"] is not None
    )
    router_comparison = paired(rows, "stage_c", "router")
    memory_comparison = paired(rows, "stage_c", "memory")
    endpoint_outcomes = paired(rows, "rag", "memory")
    return {
        "pairs": len(rows),
        "disagreements_checked": len(disagreements),
        "systems": {
            field: metrics(rows, field)
            for field in ("rag", "memory", "router", "stage_c")
        },
        "endpoint_oracle_accuracy": (
            (len(rows) - endpoint_outcomes["neither_correct"]) / len(rows) if rows else None
        ),
        "stage_c_vs_router": router_comparison,
        "stage_c_vs_memory": memory_comparison,
        "stage_c_vs_rag": paired(rows, "stage_c", "rag"),
        "stage_c_changes_from_router": sum(row["stage_c"] != row["router"] for row in rows),
        "stage_c_changes_from_memory": sum(row["stage_c"] != row["memory"] for row in rows),
        "retrieval_only_cases_recovered": sum(
            row["rag"] == row["gold"] and row["memory"] != row["gold"] and row["stage_c"] == row["gold"]
            for row in rows
        ),
        "memory_only_cases_sacrificed": sum(
            row["memory"] == row["gold"] and row["rag"] != row["gold"] and row["stage_c"] != row["gold"]
            for row in rows
        ),
        "proposition_knowledge_basis": dict(sorted(proposition_bases.items())),
        "proposition_verdicts": dict(sorted(proposition_verdicts.items())),
        "generic_claim_check_fallbacks": sum(
            bool(row["proposition_fallback"]) for row in disagreements
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--router-root", type=Path, default=Path("artifacts/runs/stage3/stage3_same_model_ab_v1")
    )
    parser.add_argument(
        "--run-root", type=Path, default=Path("artifacts/runs/stage4/stage4_same_model_c_v1")
    )
    parser.add_argument("--labels", type=Path, default=Path("artifacts/evaluation/stage1_labels.json"))
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/evaluation/stage4_same_model_c_v1.json")
    )
    parser.add_argument(
        "--attacked-condition",
        default="fact2fiction_p0.01",
        help="Attacked condition paired with clean for the success gate.",
    )
    args = parser.parse_args()
    router_manifest = json.loads((args.router_root / "private_manifest.json").read_text(encoding="utf-8"))
    manifest = json.loads((args.run_root / "private_manifest.json").read_text(encoding="utf-8"))
    if router_manifest["dry_run"] or router_manifest["failures"] or manifest["failures"]:
        raise ValueError("Input manifests are incomplete, dry-run, or contain failures")
    labels = json.loads(args.labels.read_text(encoding="utf-8"))["development"]
    c_outputs = {row["aligned_packet_key"]: row for row in manifest["outputs"]}
    rows = []
    for row in router_manifest["outputs"]:
        if row["variant"] != manifest["variant"]:
            continue
        if row["condition_id"] not in manifest["conditions"] or row["victim_model_id"] not in manifest["models"]:
            continue
        packet = json.loads(Path(row["aligned_packet_path"]).read_text(encoding="utf-8"))
        router_output = json.loads(Path(row["output_path"]).read_text(encoding="utf-8"))
        rag = packet["visible"]["retrieval_assessment"]["verdict"]
        memory = candidate_prediction(packet["visible"]["memory_only_assessment"])
        stage_c = router_output["derived_prediction"]
        proposition_basis = None
        proposition_verdict = None
        proposition_fallback = None
        if rag != memory:
            descriptor = c_outputs.get(packet["packet_key"])
            if descriptor is None:
                raise ValueError(f"Missing Stage C disagreement output: {packet['packet_key']}")
            output = json.loads(Path(descriptor["output_path"]).read_text(encoding="utf-8"))
            stage_c = output["derived_prediction"]
            proposition_basis = output["proposition_check"]["judgment"]["knowledge_basis"]
            proposition_verdict = output["proposition_check"]["judgment"]["verdict"]
            proposition_fallback = output["proposition_check"].get(
                "proposition_fallback",
                output["proposition_check"].get("proposition")
                == "Whether the original claim's central factual assertion is accurate as stated.",
            )
        rows.append(
            {
                "claim_id": row["claim_id"],
                "model_id": row["victim_model_id"],
                "condition_id": row["condition_id"],
                "gold": labels[str(row["claim_id"])],
                "rag": rag,
                "memory": memory,
                "router": router_output["derived_prediction"],
                "stage_c": stage_c,
                "proposition_basis": proposition_basis,
                "proposition_verdict": proposition_verdict,
                "proposition_fallback": proposition_fallback,
            }
        )
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["model_id"], row["condition_id"])].append(row)
    result: dict[str, Any] = {
        "evaluation_schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "router_experiment_id": manifest["router_experiment_id"],
        "variant": manifest["variant"],
        "attacked_condition": args.attacked_condition,
        "warning": "OFFLINE METHOD-DESIGN EVALUATION; gold was joined only here",
        "by_model_condition": {},
    }
    for model in sorted({key[0] for key in grouped}):
        conditions = {
            condition: summarize(grouped[(model, condition)])
            for condition in sorted(key[1] for key in grouped if key[0] == model)
        }
        clean = conditions.get("clean")
        attacked = conditions.get(args.attacked_condition)
        gate = None
        if clean and attacked:
            attacked_stage_c = attacked["systems"]["stage_c"]["accuracy"]
            attacked_best = max(
                attacked["systems"]["rag"]["accuracy"], attacked["systems"]["memory"]["accuracy"]
            )
            clean_stage_c = clean["systems"]["stage_c"]["accuracy"]
            clean_best = max(clean["systems"]["rag"]["accuracy"], clean["systems"]["memory"]["accuracy"])
            gate = {
                "attacked_condition": args.attacked_condition,
                "beats_both_endpoints": attacked_stage_c > attacked_best,
                "attacked_delta_from_best": attacked_stage_c - attacked_best,
                "clean_delta_from_best": clean_stage_c - clean_best,
                "clean_loss_within_2_points": clean_stage_c >= clean_best - 0.02,
                "passes": attacked_stage_c > attacked_best and clean_stage_c >= clean_best - 0.02,
            }
        result["by_model_condition"][model] = {"conditions": conditions, "success_gate": gate}
    atomic_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
