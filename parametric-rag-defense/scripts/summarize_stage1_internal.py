#!/usr/bin/env python3
"""Evaluate completed Stage 1 internal outputs; gold is joined only in this script."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from parametric_rag_defense.labels import (
    accuracy,
    canonical_label,
    deterministic_majority,
    macro_f1,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--dataset",
        type=Path,
        help="Dataset JSON; defaults to dataset.source in config",
    )
    parser.add_argument("--split", help="Split-manifest key; defaults to dataset.active_split")
    parser.add_argument("--claims", help="Optional comma-separated claim IDs for a pilot summary")
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    args.split = args.split or config["dataset"].get("active_split", "development")
    args.dataset = args.dataset or Path(config["dataset"]["source"])
    split = json.loads(Path(config["dataset"]["split_manifest"]).read_text(encoding="utf-8"))
    claim_ids = list(split[args.split]["claim_ids"])
    if args.claims:
        selected = {int(value) for value in args.claims.split(",")}
        claim_ids = [claim_id for claim_id in claim_ids if claim_id in selected]
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    label_mapping = config["dataset"].get("label_mapping", {})
    cache_root = Path(config["cache_root"])
    manifest_root = Path(config["run_root"]) / args.split / "internal_endpoint"

    results: dict[str, Any] = {
        "summary_schema_version": 1,
        "split": args.split,
        "claim_ids": claim_ids,
        "gold_joined_only_for_evaluation": True,
        "models": {},
    }
    for model in config["models"]:
        if "internal" not in model["roles"] or not model.get("enabled", True):
            continue
        manifest_path = manifest_root / f"{model['id']}.json"
        if not manifest_path.exists():
            results["models"][model["id"]] = {"status": "missing_manifest"}
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows_by_claim: dict[int, list[dict[str, Any]]] = {claim_id: [] for claim_id in claim_ids}
        for row in manifest.get("outputs", []):
            if row["claim_id"] in rows_by_claim:
                rows_by_claim[row["claim_id"]].append(row)

        gold: list[str] = []
        majority_predictions: list[str] = []
        unanimous = 0
        basis_counts: Counter[str] = Counter()
        confidence_values: list[float] = []
        missing_pairs = 0
        contract_failures = 0
        per_claim: list[dict[str, Any]] = []
        for claim_id in claim_ids:
            predictions: list[str] = []
            for row in rows_by_claim[claim_id]:
                if not row.get("contract_ok"):
                    contract_failures += 1
                    continue
                key = row["cache_key"]
                entry_path = cache_root / "entries" / key[:2] / f"{key}.json"
                entry = json.loads(entry_path.read_text(encoding="utf-8"))
                parsed = entry["response"]["parsed"]
                predictions.append(canonical_label(parsed["verdict"]))
                basis_counts[parsed["knowledge_basis"]] += 1
                confidence_values.append(float(parsed["confidence"]))
            expected_repeats = len(config["decoding"]["internal"]["seeds"])
            missing_pairs += expected_repeats - len(rows_by_claim[claim_id])
            if not predictions:
                continue
            majority = deterministic_majority(predictions)
            expected = canonical_label(dataset[claim_id]["label"], label_mapping)
            gold.append(expected)
            majority_predictions.append(majority)
            unanimous += len(set(predictions)) == 1
            per_claim.append(
                {
                    "claim_id": claim_id,
                    "gold": expected,
                    "sample_verdicts": predictions,
                    "majority_verdict": majority,
                    "correct": majority == expected,
                }
            )

        complete_claims = len(majority_predictions)
        per_label_accuracy: dict[str, float | None] = {}
        for label in config["dataset"]["labels"]:
            indices = [index for index, expected in enumerate(gold) if expected == label]
            per_label_accuracy[label] = (
                sum(majority_predictions[index] == label for index in indices) / len(indices)
                if indices
                else None
            )
        results["models"][model["id"]] = {
            "status": "complete" if missing_pairs == 0 and contract_failures == 0 else "partial",
            "evaluated_claims": complete_claims,
            "requested_claims": len(claim_ids),
            "missing_pairs": missing_pairs,
            "contract_failures": contract_failures,
            "majority_accuracy": accuracy(gold, majority_predictions) if gold else None,
            "majority_macro_f1": macro_f1(gold, majority_predictions) if gold else None,
            "unanimous_rate": unanimous / complete_claims if complete_claims else None,
            "mean_reported_confidence": (
                sum(confidence_values) / len(confidence_values) if confidence_values else None
            ),
            "knowledge_basis_counts": dict(sorted(basis_counts.items())),
            "prediction_counts": dict(sorted(Counter(majority_predictions).items())),
            "per_label_accuracy": per_label_accuracy,
            "per_claim": per_claim,
        }

    complete_models = [
        model_id
        for model_id, row in results["models"].items()
        if row.get("status") == "complete" and row.get("per_claim")
    ]
    if complete_models:
        per_model_claims = {
            model_id: {row["claim_id"]: row for row in results["models"][model_id]["per_claim"]}
            for model_id in complete_models
        }
        common_claims = sorted(
            set.intersection(*(set(rows) for rows in per_model_claims.values()))
        )
        ensemble_gold: list[str] = []
        ensemble_predictions: list[str] = []
        oracle_correct = 0
        all_models_agree = 0
        for claim_id in common_claims:
            predictions = [
                per_model_claims[model_id][claim_id]["majority_verdict"]
                for model_id in complete_models
            ]
            expected = per_model_claims[complete_models[0]][claim_id]["gold"]
            ensemble_gold.append(expected)
            ensemble_predictions.append(deterministic_majority(predictions))
            oracle_correct += expected in predictions
            all_models_agree += len(set(predictions)) == 1
        pairwise: list[dict[str, Any]] = []
        for index, first in enumerate(complete_models):
            for second in complete_models[index + 1 :]:
                disagreements = [
                    claim_id
                    for claim_id in common_claims
                    if per_model_claims[first][claim_id]["majority_verdict"]
                    != per_model_claims[second][claim_id]["majority_verdict"]
                ]
                pairwise.append(
                    {
                        "first_model": first,
                        "second_model": second,
                        "disagreement_count": len(disagreements),
                        "first_only_correct": sum(
                            per_model_claims[first][claim_id]["correct"]
                            and not per_model_claims[second][claim_id]["correct"]
                            for claim_id in disagreements
                        ),
                        "second_only_correct": sum(
                            per_model_claims[second][claim_id]["correct"]
                            and not per_model_claims[first][claim_id]["correct"]
                            for claim_id in disagreements
                        ),
                    }
                )
        results["cross_model_diagnostic"] = {
            "models": complete_models,
            "claims": len(common_claims),
            "majority_ensemble_accuracy": accuracy(ensemble_gold, ensemble_predictions),
            "majority_ensemble_macro_f1": macro_f1(ensemble_gold, ensemble_predictions),
            "oracle_any_model_correct": oracle_correct / len(common_claims),
            "all_models_agree_rate": all_models_agree / len(common_claims),
            "pairwise": pairwise,
            "interpretation": (
                "The oracle is diagnostic headroom, not a deployable result; compare it with the "
                "majority ensemble to test whether arbitration rather than voting is warranted."
            ),
        }

    rendered = json.dumps(results, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
