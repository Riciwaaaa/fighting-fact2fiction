#!/usr/bin/env python3
"""Fit the frozen development meta-router and transfer it to prior locked artifacts.

The locked set was opened for earlier workflows, so this is retrospective transfer evidence, not
new confirmation. The script requires an explicit flag to prevent accidental use.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from diagnose_low_rate_aggregation import (
    ENDPOINT_FEATURE_NAMES,
    endpoint_features,
    estimator_factories,
    grouped_predictions,
    load_rows,
)
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.labels import canonical_label, deterministic_majority


def exact_paired_pvalue(left_only: int, right_only: int) -> float:
    discordant = left_only + right_only
    if not discordant:
        return 1.0
    tail = sum(math.comb(discordant, value) for value in range(min(left_only, right_only) + 1))
    return min(1.0, 2.0 * tail / (2**discordant))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    systems = ("rag", "memory", "answerability", "router", "oracle")
    result: dict[str, Any] = {
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
            for system in systems
        },
    }
    disagreements = [row for row in rows if row["rag_prediction"] != row["memory_prediction"]]
    result["endpoint_disagreements"] = len(disagreements)
    result["router_actions_on_disagreements"] = dict(
        sorted(Counter(row["router_action"] for row in disagreements).items())
    )
    for baseline in ("rag", "memory", "answerability"):
        router_only = sum(
            row["router_correct"] and not row[f"{baseline}_correct"] for row in rows
        )
        baseline_only = sum(
            row[f"{baseline}_correct"] and not row["router_correct"] for row in rows
        )
        result[f"router_vs_{baseline}"] = {
            "router_only_correct": router_only,
            f"{baseline}_only_correct": baseline_only,
            "net": router_only - baseline_only,
            "exact_p": exact_paired_pvalue(router_only, baseline_only),
        }
    return result


def load_endpoint_map(roots: list[Path]) -> dict[str, dict[str, Any]]:
    result = {}
    for root in roots:
        for path in root.glob("*/*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            key = str(value["task_key"])
            if key in result:
                raise ValueError(f"Duplicate locked endpoint task key: {key}")
            result[key] = value
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--development-run-root",
        type=Path,
        default=Path("artifacts/runs/evidence_signal/evidence_signal_v1"),
    )
    parser.add_argument(
        "--locked-index",
        type=Path,
        default=Path(
            "artifacts/runs/stage3/stage3_locked_neutral_inputs_v1/private_index.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluation/calibrated_router_transfer_v1.json"),
    )
    parser.add_argument("--allow-retrospective-locked", action="store_true")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    dataset = json.loads(Path(config["dataset"]["source"]).read_text(encoding="utf-8"))
    development_args = argparse.Namespace(
        config=args.config, run_root=args.development_run_root
    )
    development_rows = load_rows(development_args)
    train_rows = [
        row for row in development_rows if row["rag_correct"] != row["memory_correct"]
    ]
    estimator = estimator_factories()["logistic_prior"]()
    estimator.fit(
        [endpoint_features(row) for row in train_rows],
        [int(row["rag_correct"]) for row in train_rows],
    )
    oof = grouped_predictions(development_rows, "endpoint", "logistic_prior")
    scaler = estimator.named_steps["standardscaler"]
    logistic = estimator.named_steps["logisticregression"]
    fitted_model = {
        "feature_names": list(ENDPOINT_FEATURE_NAMES),
        "standard_scaler_mean": [float(value) for value in scaler.mean_],
        "standard_scaler_scale": [float(value) for value in scaler.scale_],
        "logistic_coefficients": [float(value) for value in logistic.coef_[0]],
        "logistic_intercept": float(logistic.intercept_[0]),
        "rag_probability_threshold": 0.5,
        "training_rows": len(train_rows),
        "training_unique_claims": len({row["claim_id"] for row in train_rows}),
    }
    if not args.allow_retrospective_locked:
        print(
            json.dumps(
                {
                    "status": "prepared_without_locked_evaluation",
                    "development_oof": {
                        key: value
                        for key, value in oof.items()
                        if key != "private_predictions"
                    },
                    "fitted_model": fitted_model,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    locked_index = json.loads(args.locked_index.read_text(encoding="utf-8"))
    endpoints = load_endpoint_map(
        [
            Path(
                "artifacts/runs/stage1/locked_test/rag/stage1_locked_confirm_v1/endpoints"
            ),
            Path(
                "artifacts/runs/stage1/locked_test/rag/stage1_locked_crossed_1pct_v1/endpoints"
            ),
        ]
    )
    rows = []
    for descriptor in locked_index["rows"]:
        endpoint = endpoints[descriptor["rag_task_key"]]
        packet = json.loads(
            Path(descriptor["aligned_packet_path"]).read_text(encoding="utf-8")
        )["visible"]
        internal_samples = packet["memory_only_assessment"]["samples"]
        memory_prediction = deterministic_majority(
            sample["verdict"] for sample in internal_samples
        )
        rag_prediction = endpoint["judgment"]["verdict"]
        feature_row = {
            "internal_samples": internal_samples,
            "endpoint_judgment": endpoint["judgment"],
        }
        probability = float(
            estimator.predict_proba([endpoint_features(feature_row)])[0, 1]
        )
        if rag_prediction == memory_prediction:
            router_action = "agreement"
            router_prediction = rag_prediction
        else:
            router_action = "rag" if probability >= 0.5 else "memory"
            router_prediction = (
                rag_prediction if router_action == "rag" else memory_prediction
            )
        answerability_action = (
            "memory"
            if memory_prediction in {"Supported", "Refuted"}
            else "rag"
        )
        answerability_prediction = (
            memory_prediction if answerability_action == "memory" else rag_prediction
        )
        claim_id = int(descriptor["claim_id"])
        gold = canonical_label(
            dataset[claim_id]["label"], config["dataset"]["label_mapping"]
        )
        rows.append(
            {
                "claim_id": claim_id,
                "victim_model_id": descriptor["victim_model_id"],
                "attacker_model_id": descriptor["attacker_model_id"],
                "condition_id": descriptor["condition_id"],
                "gold": gold,
                "rag_prediction": rag_prediction,
                "memory_prediction": memory_prediction,
                "answerability_prediction": answerability_prediction,
                "router_prediction": router_prediction,
                "answerability_action": answerability_action,
                "router_action": router_action,
                "router_rag_probability": probability,
                "rag_correct": rag_prediction == gold,
                "memory_correct": memory_prediction == gold,
                "answerability_correct": answerability_prediction == gold,
                "router_correct": router_prediction == gold,
                "oracle_correct": rag_prediction == gold or memory_prediction == gold,
            }
        )
    clean = [row for row in rows if row["condition_id"] == "clean"]
    attacked = [row for row in rows if row["condition_id"] != "clean"]
    victims = sorted({row["victim_model_id"] for row in rows})
    attackers = sorted(
        {row["attacker_model_id"] for row in attacked if row["attacker_model_id"]}
    )
    output = {
        "evaluation_schema_version": 1,
        "status": "retrospective_locked_transfer_not_confirmation",
        "method": (
            "One shared condition-blind logistic router trained on endpoint-exclusive development "
            "disagreements using only closed-book calibration and RAG process metadata."
        ),
        "development_oof": {
            key: value for key, value in oof.items() if key != "private_predictions"
        },
        "fitted_model": fitted_model,
        "locked": {
            "clean": summarize(clean),
            "attacked": summarize(attacked),
            "by_victim": {
                victim: {
                    "clean": summarize(
                        [row for row in clean if row["victim_model_id"] == victim]
                    ),
                    "attacked": summarize(
                        [row for row in attacked if row["victim_model_id"] == victim]
                    ),
                }
                for victim in victims
            },
            "by_attacker": {
                attacker: summarize(
                    [row for row in attacked if row["attacker_model_id"] == attacker]
                )
                for attacker in attackers
            },
        },
        "private_rows": rows,
    }
    atomic_json(args.output, output)
    print(
        json.dumps(
            {key: value for key, value in output.items() if key != "private_rows"},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
