#!/usr/bin/env python3
"""Join cached Stage 1 endpoint evaluations and quantify defense headroom."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json


def safe_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def wilson95(successes: int, total: int) -> list[float] | None:
    """Return a two-sided 95% Wilson score interval for a binomial proportion."""

    if not total:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    ) / denominator
    return [center - radius, center + radius]


def merge_scans(scans: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge disjoint rate scans after checking their common experimental identity."""

    if not scans:
        raise ValueError("At least one scan is required")
    reference = scans[0]
    merged: dict[str, Any] = {
        "evaluation_schema_version": reference["evaluation_schema_version"],
        "split": reference["split"],
        "rates": [],
        "models": {model_id: {"levels": {}} for model_id in reference["models"]},
    }
    reference_models = set(reference["models"])
    seen_conditions: set[str] = set()
    for scan in scans:
        if scan["split"] != reference["split"]:
            raise ValueError("Cannot merge scans from different splits")
        if set(scan["models"]) != reference_models:
            raise ValueError("Cannot merge scans with different model sets")
        merged["rates"].extend(float(rate) for rate in scan["rates"])
        for model_id, model_scan in scan["models"].items():
            for condition_id, level in model_scan["levels"].items():
                identity = f"{model_id}:{condition_id}"
                if identity in seen_conditions:
                    raise ValueError(f"Duplicate scan condition: {identity}")
                seen_conditions.add(identity)
                merged["models"][model_id]["levels"][condition_id] = level
    merged["rates"] = sorted(set(merged["rates"]))
    for model_scan in merged["models"].values():
        model_scan["levels"] = dict(
            sorted(
                model_scan["levels"].items(),
                key=lambda item: float(item[0].rsplit("p", 1)[1]),
            )
        )
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--internal", type=Path,
        default=Path("artifacts/evaluation/stage1_internal_development.json"),
    )
    parser.add_argument(
        "--eligibility", type=Path,
    )
    parser.add_argument(
        "--scan",
        type=Path,
        action="append",
        help="Gold-joined RAG scan. Repeat to combine disjoint rate scans.",
    )
    parser.add_argument(
        "--output", type=Path,
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    namespace = config["rag_pipeline"]["artifact_namespace"]
    args.eligibility = args.eligibility or Path(
        f"artifacts/evaluation/{namespace}_clean_eligibility.json"
    )
    args.scan = args.scan or [Path(f"artifacts/evaluation/{namespace}_initial_scan.json")]
    args.output = args.output or Path(
        f"artifacts/evaluation/{namespace}_endpoint_complementarity.json"
    )
    internal = json.loads(args.internal.read_text(encoding="utf-8"))
    eligibility = json.loads(args.eligibility.read_text(encoding="utf-8"))
    scan = merge_scans(
        [json.loads(path.read_text(encoding="utf-8")) for path in args.scan]
    )
    internal_predictions = {
        model_id: {str(row["claim_id"]): row["majority_verdict"] for row in result["per_claim"]}
        for model_id, result in internal["models"].items()
    }
    gold = {
        str(row["claim_id"]): row["gold"]
        for result in internal["models"].values()
        for row in result["per_claim"]
    }
    majority_predictions: dict[str, str] = {}
    all_internal_oracle: dict[str, bool] = {}
    model_ids = sorted(internal_predictions)
    for claim_id in gold:
        values = [internal_predictions[model_id][claim_id] for model_id in model_ids]
        supported = sum(value == "Supported" for value in values)
        majority_predictions[claim_id] = "Supported" if supported >= 2 else "Refuted"
        all_internal_oracle[claim_id] = any(
            internal_predictions[model_id][claim_id] == gold[claim_id] for model_id in model_ids
        )

    output: dict[str, Any] = {
        "summary_schema_version": 3,
        "split": "development",
        "rates": scan["rates"],
        "source_scans": [str(path) for path in args.scan],
        "interpretation": (
            "Oracle values measure complementarity/headroom and are not deployable defense results. "
            "A Stage 3 workflow must exceed both standalone endpoints without using gold."
        ),
        "models": {},
        "aggregate": {
            "aggregation": "Micro-average over eligible victim-model/claim pairs; a claim may appear for multiple victims.",
            "levels": {},
        },
    }
    aggregate: dict[str, dict[str, Any]] = {}
    rag_correctness_paths: dict[tuple[str, str], dict[str, bool]] = {}
    for model_id, model_scan in scan["models"].items():
        eligible = [str(value) for value in eligibility["models"][model_id]["eligible_claim_ids"]]
        model_result: dict[str, Any] = {
            "full_development": {
                "model_only_accuracy": internal["models"][model_id]["majority_accuracy"],
                "clean_rag_accuracy": eligibility["models"][model_id]["clean_accuracy"],
                "clean_rag_completed": eligibility["models"][model_id]["completed"],
            },
            "clean_correct_subset_size": len(eligible),
            "levels": {},
        }
        for condition_id, level in model_scan["levels"].items():
            paired_claims = [claim_id for claim_id in eligible if claim_id in level["predictions"]]
            counts = {"both_correct": 0, "rag_only_correct": 0, "internal_only_correct": 0, "neither_correct": 0}
            panel_counts = {
                "both_correct": 0,
                "rag_only_correct": 0,
                "panel_only_correct": 0,
                "neither_correct": 0,
            }
            internal_majority_correct = 0
            all_internal_any_correct = 0
            for claim_id in paired_claims:
                rag_correct = level["predictions"][claim_id] == gold[claim_id]
                rag_correctness_paths.setdefault((model_id, claim_id), {})[
                    condition_id
                ] = rag_correct
                internal_correct = internal_predictions[model_id][claim_id] == gold[claim_id]
                panel_correct = majority_predictions[claim_id] == gold[claim_id]
                if rag_correct and internal_correct:
                    counts["both_correct"] += 1
                elif rag_correct:
                    counts["rag_only_correct"] += 1
                elif internal_correct:
                    counts["internal_only_correct"] += 1
                else:
                    counts["neither_correct"] += 1
                if rag_correct and panel_correct:
                    panel_counts["both_correct"] += 1
                elif rag_correct:
                    panel_counts["rag_only_correct"] += 1
                elif panel_correct:
                    panel_counts["panel_only_correct"] += 1
                else:
                    panel_counts["neither_correct"] += 1
                internal_majority_correct += int(majority_predictions[claim_id] == gold[claim_id])
                all_internal_any_correct += int(all_internal_oracle[claim_id])
            total = len(paired_claims)
            same_internal_correct = counts["both_correct"] + counts["internal_only_correct"]
            rag_correct = counts["both_correct"] + counts["rag_only_correct"]
            rag_wrong = total - rag_correct
            all_internal_oracle_correct = all_internal_any_correct + rag_correct - sum(
                int(all_internal_oracle[claim_id] and level["predictions"][claim_id] == gold[claim_id])
                for claim_id in paired_claims
            )
            model_result["levels"][condition_id] = {
                "paired_claims": total,
                "poisoned_rag_accuracy": safe_rate(rag_correct, total),
                "same_model_internal_accuracy": safe_rate(same_internal_correct, total),
                "internal_majority_accuracy": safe_rate(internal_majority_correct, total),
                "same_model_oracle_accuracy": safe_rate(total - counts["neither_correct"], total),
                "all_internal_oracle_accuracy": safe_rate(all_internal_oracle_correct, total),
                "panel_plus_rag_oracle_accuracy": safe_rate(
                    total - panel_counts["neither_correct"], total
                ),
                "same_model_rescue_rate_when_rag_wrong": safe_rate(counts["internal_only_correct"], rag_wrong),
                "endpoint_outcomes": counts,
                "panel_endpoint_outcomes": panel_counts,
                "mean_poison_documents_injected": level["mean_poison_documents_injected"],
                "retrieved_poison_fraction": level["retrieved_poison_fraction"],
                "mean_realized_poison_fraction": level["mean_realized_poison_fraction"],
            }
            combined = aggregate.setdefault(
                condition_id,
                {
                    "paired_claims": 0,
                    "rag_correct": 0,
                    "same_internal_correct": 0,
                    "internal_majority_correct": 0,
                    "same_model_oracle_correct": 0,
                    "all_internal_oracle_correct": 0,
                    "rag_wrong": 0,
                    "same_model_rescues": 0,
                    "endpoint_outcomes": {
                        "both_correct": 0,
                        "rag_only_correct": 0,
                        "internal_only_correct": 0,
                        "neither_correct": 0,
                    },
                    "panel_endpoint_outcomes": {
                        "both_correct": 0,
                        "rag_only_correct": 0,
                        "panel_only_correct": 0,
                        "neither_correct": 0,
                    },
                    "panel_plus_rag_oracle_correct": 0,
                    "poison_documents_weighted": 0.0,
                    "retrieved_poison_weighted": 0.0,
                    "realized_poison_weighted": 0.0,
                },
            )
            combined["paired_claims"] += total
            combined["rag_correct"] += rag_correct
            combined["same_internal_correct"] += same_internal_correct
            combined["internal_majority_correct"] += internal_majority_correct
            combined["same_model_oracle_correct"] += total - counts["neither_correct"]
            combined["all_internal_oracle_correct"] += all_internal_oracle_correct
            combined["rag_wrong"] += rag_wrong
            combined["same_model_rescues"] += counts["internal_only_correct"]
            for name, count in counts.items():
                combined["endpoint_outcomes"][name] += count
            for name, count in panel_counts.items():
                combined["panel_endpoint_outcomes"][name] += count
            combined["panel_plus_rag_oracle_correct"] += total - panel_counts["neither_correct"]
            combined["poison_documents_weighted"] += level["mean_poison_documents_injected"] * total
            combined["retrieved_poison_weighted"] += level["retrieved_poison_fraction"] * total
            combined["realized_poison_weighted"] += level["mean_realized_poison_fraction"] * total
        output["models"][model_id] = model_result
    for condition_id, combined in aggregate.items():
        total = combined["paired_claims"]
        output["aggregate"]["levels"][condition_id] = {
            "paired_claims": total,
            "poisoned_rag_accuracy": safe_rate(combined["rag_correct"], total),
            "poisoned_rag_accuracy_wilson95": wilson95(combined["rag_correct"], total),
            "same_model_internal_accuracy": safe_rate(combined["same_internal_correct"], total),
            "internal_majority_accuracy": safe_rate(combined["internal_majority_correct"], total),
            "same_model_oracle_accuracy": safe_rate(combined["same_model_oracle_correct"], total),
            "all_internal_oracle_accuracy": safe_rate(combined["all_internal_oracle_correct"], total),
            "panel_plus_rag_oracle_accuracy": safe_rate(
                combined["panel_plus_rag_oracle_correct"], total
            ),
            "same_model_rescue_rate_when_rag_wrong": safe_rate(
                combined["same_model_rescues"], combined["rag_wrong"]
            ),
            "endpoint_outcomes": combined["endpoint_outcomes"],
            "panel_endpoint_outcomes": combined["panel_endpoint_outcomes"],
            "mean_poison_documents_injected": combined["poison_documents_weighted"] / total,
            "retrieved_poison_fraction": combined["retrieved_poison_weighted"] / total,
            "mean_realized_poison_fraction": combined["realized_poison_weighted"] / total,
        }
    condition_order = list(next(iter(scan["models"].values()))["levels"])
    transitions: list[dict[str, Any]] = []
    for lower, higher in zip(condition_order, condition_order[1:]):
        counts = {
            "correct_at_both": 0,
            "correct_to_wrong": 0,
            "wrong_to_correct": 0,
            "wrong_at_both": 0,
        }
        for path in rag_correctness_paths.values():
            if lower not in path or higher not in path:
                continue
            if path[lower] and path[higher]:
                counts["correct_at_both"] += 1
            elif path[lower]:
                counts["correct_to_wrong"] += 1
            elif path[higher]:
                counts["wrong_to_correct"] += 1
            else:
                counts["wrong_at_both"] += 1
        transitions.append({"lower": lower, "higher": higher, **counts})
    nonmonotonic_paths = 0
    for path in rag_correctness_paths.values():
        ordered = [path[condition] for condition in condition_order if condition in path]
        nonmonotonic_paths += int(
            any(not lower and higher for lower, higher in zip(ordered, ordered[1:]))
        )
    output["aggregate"]["adjacent_rate_transitions"] = transitions
    output["aggregate"]["nonmonotonic_rag_paths"] = nonmonotonic_paths
    output["aggregate"]["total_rag_paths"] = len(rag_correctness_paths)
    atomic_json(args.output.resolve(), output)
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
