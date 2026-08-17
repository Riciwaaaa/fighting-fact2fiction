#!/usr/bin/env python3
"""Diagnose observable endpoint-selection signals on cached low-rate disagreements.

This is explicitly post-label method development. It does not produce a frozen defense result.
All cross-validation folds are grouped by claim so repeated rates/models for one claim never cross
the train/test boundary.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Callable

from build_stage2_packets import internal_lookup
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.labels import canonical_label, deterministic_majority
from summarize_evidence_signal import row_features

CONDITIONS = (
    "clean",
    "fact2fiction_p0.001",
    "fact2fiction_p0.0025",
    "fact2fiction_p0.005",
)

ENDPOINT_FEATURE_NAMES = (
    "memory_vote_share",
    "memory_confidence_mean",
    "memory_confidence_min",
    "memory_confidence_max",
    "memory_confidence_std",
    "memory_basis_direct_recall_share",
    "memory_basis_inference_share",
    "memory_basis_insufficient_share",
    "memory_premise_concern_count_mean",
    "memory_decisive_proposition_count_mean",
    "memory_rationale_pair_jaccard",
    "rag_confidence",
    "rag_answered_question_share",
    "rag_evidence_count_mean",
    "rag_evidence_count_max",
    "rag_selected_rank_mean",
    "rag_selected_rank_max",
    "rag_selected_rank1_share",
    "rag_justification_log_length",
    "rag_answer_log_length_mean",
)


def safe_rate(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def mean_pair_jaccard(values: list[str]) -> float:
    token_sets = [words(value) for value in values]
    scores = []
    for left_index, left in enumerate(token_sets):
        for right in token_sets[left_index + 1 :]:
            scores.append(safe_rate(len(left & right), len(left | right)))
    return mean(scores) if scores else 1.0


def endpoint_features(row: dict[str, Any]) -> list[float]:
    samples = row["internal_samples"]
    confidences = [float(sample["confidence"]) for sample in samples]
    votes = Counter(sample["verdict"] for sample in samples)
    bases = Counter(sample["knowledge_basis"] for sample in samples)
    endpoint = row["endpoint_judgment"]
    questions = endpoint["questions"]
    answered = [item for item in questions if item["status"] == "answered"]
    selected_ranks = [
        int(item["selected_rank"])
        for item in answered
        if item["selected_rank"] is not None
    ]
    evidence_counts = [len(item["evidence"]) for item in questions]
    result = [
        max(votes.values()) / len(samples),
        mean(confidences),
        min(confidences),
        max(confidences),
        pstdev(confidences),
        safe_rate(bases["direct_recall"], len(samples)),
        safe_rate(bases["inference"], len(samples)),
        safe_rate(bases["insufficient_knowledge"], len(samples)),
        mean(len(sample["premise_concerns"]) for sample in samples),
        mean(len(sample["decisive_propositions"]) for sample in samples),
        mean_pair_jaccard([sample["rationale"] for sample in samples]),
        float(endpoint["confidence"]),
        safe_rate(len(answered), len(questions)),
        mean(evidence_counts),
        max(evidence_counts, default=0),
        mean(selected_ranks) if selected_ranks else 0.0,
        max(selected_ranks, default=0),
        safe_rate(sum(rank == 1 for rank in selected_ranks), len(selected_ranks)),
        math.log1p(len(endpoint["justification"])),
        mean(math.log1p(len(item["answer"] or "")) for item in questions),
    ]
    if len(result) != len(ENDPOINT_FEATURE_NAMES):
        raise AssertionError("Endpoint feature name/vector mismatch")
    return result


def retrieval_features(row: dict[str, Any]) -> list[float]:
    groups = row["trace"]["retrievals"]
    retrieved = [item for group in groups for item in group]
    distances = [float(item["distance"]) for item in retrieved]
    group_sizes = [len(group) for group in groups]
    unique_hashes = {item["text_sha256"] for item in retrieved}
    return [
        float(len(retrieved)),
        float(len(unique_hashes)),
        safe_rate(len(retrieved) - len(unique_hashes), len(retrieved)),
        safe_rate(sum(not size for size in group_sizes), len(group_sizes)),
        mean(group_sizes),
        pstdev(group_sizes),
        mean(distances),
        min(distances),
        max(distances),
        pstdev(distances),
    ]


def feature_vector(row: dict[str, Any], feature_set: str) -> list[float]:
    passage = row_features(row, include_endpoint_alignment=True)
    endpoint = endpoint_features(row)
    retrieval = retrieval_features(row)
    if feature_set == "passage":
        return passage
    if feature_set == "endpoint":
        return endpoint
    if feature_set == "endpoint_retrieval":
        return endpoint + retrieval
    if feature_set == "combined":
        return endpoint + retrieval + passage
    raise ValueError(f"Unknown feature set: {feature_set}")


def cluster_bootstrap_delta(
    truths: list[int], predictions: list[int], groups: list[int], constant: int
) -> list[float]:
    values: dict[int, list[int]] = defaultdict(list)
    for truth, prediction, group in zip(truths, predictions, groups):
        values[group].append(int(prediction == truth) - int(constant == truth))
    rng = random.Random(20260811)
    unique = sorted(values)
    samples = []
    for _ in range(5000):
        selected = rng.choices(unique, k=len(unique))
        deltas = [value for group in selected for value in values[group]]
        samples.append(sum(deltas) / len(deltas))
    samples.sort()
    return [samples[int(0.025 * len(samples))], samples[int(0.975 * len(samples)) - 1]]


def estimator_factories() -> dict[str, Callable[[], Any]]:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return {
        "logistic_prior": lambda: make_pipeline(
            StandardScaler(),
            LogisticRegression(C=0.3, max_iter=3000, random_state=20260811),
        ),
        "logistic_balanced": lambda: make_pipeline(
            StandardScaler(),
            LogisticRegression(
                C=0.3, class_weight="balanced", max_iter=3000, random_state=20260811
            ),
        ),
        "random_forest_shallow": lambda: RandomForestClassifier(
            n_estimators=400,
            max_depth=3,
            min_samples_leaf=5,
            max_features="sqrt",
            class_weight=None,
            random_state=20260811,
            n_jobs=1,
        ),
    }


def grouped_predictions(
    rows: list[dict[str, Any]], feature_set: str, estimator_name: str
) -> dict[str, Any]:
    from sklearn.metrics import accuracy_score, balanced_accuracy_score, roc_auc_score
    from sklearn.model_selection import StratifiedGroupKFold

    exclusive = [row for row in rows if row["rag_correct"] != row["memory_correct"]]
    y = [int(row["rag_correct"]) for row in exclusive]
    groups = [row["claim_id"] for row in exclusive]
    x = [feature_vector(row, feature_set) for row in exclusive]
    if len(exclusive) < 20 or min(Counter(y).values(), default=0) < 5:
        return {"status": "insufficient", "rows": len(exclusive)}
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=20260811)
    predictions = [0] * len(y)
    probabilities = [0.0] * len(y)
    fold_records = []
    for fold, (train, test) in enumerate(splitter.split(x, y, groups), 1):
        estimator = estimator_factories()[estimator_name]()
        estimator.fit([x[index] for index in train], [y[index] for index in train])
        fold_predictions = estimator.predict([x[index] for index in test])
        fold_probabilities = estimator.predict_proba([x[index] for index in test])[:, 1]
        for index, prediction, probability in zip(test, fold_predictions, fold_probabilities):
            predictions[int(index)] = int(prediction)
            probabilities[int(index)] = float(probability)
        fold_records.append(
            {
                "fold": fold,
                "rows": len(test),
                "unique_claims": len({groups[index] for index in test}),
                "accuracy": accuracy_score(
                    [y[index] for index in test], fold_predictions
                ),
            }
        )
    rag_cases = sum(y)
    memory_cases = len(y) - rag_cases
    constant = int(rag_cases >= memory_cases)
    constant_accuracy = max(rag_cases, memory_cases) / len(y)
    accuracy = accuracy_score(y, predictions)
    return {
        "status": "complete",
        "feature_set": feature_set,
        "estimator": estimator_name,
        "rows": len(exclusive),
        "unique_claims": len(set(groups)),
        "rag_correct_cases": rag_cases,
        "memory_correct_cases": memory_cases,
        "constant_endpoint": "rag" if constant else "memory",
        "constant_accuracy": constant_accuracy,
        "accuracy": accuracy,
        "balanced_accuracy": balanced_accuracy_score(y, predictions),
        "roc_auc": roc_auc_score(y, probabilities),
        "accuracy_delta_vs_constant": accuracy - constant_accuracy,
        "claim_cluster_bootstrap95_delta_vs_constant": cluster_bootstrap_delta(
            y, predictions, groups, constant
        ),
        "folds": fold_records,
        "private_predictions": [
            {
                "claim_id": row["claim_id"],
                "victim_model_id": row["victim_model_id"],
                "condition_id": row["condition_id"],
                "truth": truth,
                "prediction": prediction,
                "rag_probability": probability,
            }
            for row, truth, prediction, probability in zip(
                exclusive, y, predictions, probabilities
            )
        ],
    }


def load_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    config = json.loads(args.config.read_text(encoding="utf-8"))
    dataset = json.loads(Path(config["dataset"]["source"]).read_text(encoding="utf-8"))
    manifest = json.loads((args.run_root / "private_manifest.json").read_text(encoding="utf-8"))
    samples, _ = internal_lookup(
        config,
        Path("artifacts/runs/stage1/development/internal_endpoint"),
        Path(config["cache_root"]),
    )
    trace_root = Path("artifacts/runs/stage1/development/rag") / config["rag_pipeline"][
        "artifact_namespace"
    ] / "private_traces"
    rows = []
    for descriptor in manifest["rows"]:
        claim_id = int(descriptor["claim_id"])
        model_id = descriptor["victim_model_id"]
        endpoint = json.loads(Path(descriptor["endpoint_path"]).read_text(encoding="utf-8"))
        packet = json.loads(Path(descriptor["packet_path"]).read_text(encoding="utf-8"))
        output = json.loads(Path(descriptor["output_path"]).read_text(encoding="utf-8"))
        trace = json.loads(
            (trace_root / descriptor["rag_task_key"][:2] / f"{descriptor['rag_task_key']}.json").read_text(
                encoding="utf-8"
            )
        )
        gold = canonical_label(
            dataset[claim_id]["label"],
            {"Conflicting Evidence/Cherrypicking": "Conflicting Evidence"},
        )
        memory_prediction = deterministic_majority(
            sample["verdict"] for sample in samples[model_id][claim_id]
        )
        row = {
            "claim_id": claim_id,
            "victim_model_id": model_id,
            "condition_id": descriptor["condition_id"],
            "retrieval_prediction": endpoint["judgment"]["verdict"],
            "memory_prediction": memory_prediction,
            "rag_correct": endpoint["judgment"]["verdict"] == gold,
            "memory_correct": memory_prediction == gold,
            "gold": gold,
            "packet": packet,
            "judgment": output["judgment"],
            "endpoint_judgment": endpoint["judgment"],
            "internal_samples": samples[model_id][claim_id],
            "trace": trace,
        }
        rows.append(row)
    return rows


def strip_private_predictions(value: dict[str, Any]) -> dict[str, Any]:
    return {key: child for key, child in value.items() if key != "private_predictions"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("artifacts/runs/evidence_signal/evidence_signal_v1"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluation/low_rate_aggregation_diagnostic_v1.json"),
    )
    args = parser.parse_args()
    rows = load_rows(args)
    attacked = [row for row in rows if row["condition_id"] != "clean"]
    scenarios = {"attacked_pooled": attacked, "all_pooled": rows}
    for model_id in sorted({row["victim_model_id"] for row in rows}):
        scenarios[f"attacked_{model_id}"] = [
            row for row in attacked if row["victim_model_id"] == model_id
        ]
        scenarios[f"all_{model_id}"] = [
            row for row in rows if row["victim_model_id"] == model_id
        ]
    results = {}
    private_predictions = {}
    for scenario_name, scenario_rows in scenarios.items():
        results[scenario_name] = {}
        private_predictions[scenario_name] = {}
        for feature_set in ("passage", "endpoint", "endpoint_retrieval", "combined"):
            results[scenario_name][feature_set] = {}
            private_predictions[scenario_name][feature_set] = {}
            for estimator_name in estimator_factories():
                value = grouped_predictions(scenario_rows, feature_set, estimator_name)
                results[scenario_name][feature_set][estimator_name] = strip_private_predictions(
                    value
                )
                private_predictions[scenario_name][feature_set][estimator_name] = value.get(
                    "private_predictions", []
                )
    output = {
        "diagnostic_schema_version": 1,
        "status": "post_label_method_development",
        "interpretation": (
            "Exploratory claim-grouped feature diagnostic on the existing 100 development claims; "
            "candidate comparison and these scores are not independent validation."
        ),
        "conditions": list(CONDITIONS),
        "rows": len(rows),
        "results": results,
        "private_predictions": private_predictions,
    }
    atomic_json(args.output, output)
    print(json.dumps({key: value for key, value in output.items() if key != "private_predictions"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
