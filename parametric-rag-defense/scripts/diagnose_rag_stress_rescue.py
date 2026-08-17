#!/usr/bin/env python3
"""Nested claim-grouped calibration of rare rescues from the selected champion."""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from parametric_rag_defense.averitec import atomic_json

CONDITIONS = (
    "clean",
    "fact2fiction_p0.001",
    "fact2fiction_p0.0025",
    "fact2fiction_p0.005",
)


def identity(row: dict[str, Any]) -> tuple[str, int, str]:
    return row["victim_model_id"], int(row["claim_id"]), row["condition_id"]


def words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def rationale_overlap(samples: list[dict[str, Any]]) -> float:
    values = [words(sample["rationale"]) for sample in samples]
    scores = []
    for index, left in enumerate(values):
        for right in values[index + 1 :]:
            scores.append(len(left & right) / len(left | right) if left | right else 1.0)
    return mean(scores) if scores else 1.0


def relation(label: str | None, *, rag: str, memory: str) -> tuple[float, float, float]:
    return (
        float(label == rag),
        float(label == memory),
        float(label not in {rag, memory}),
    )


def base_features(row: dict[str, Any]) -> list[float]:
    visible = row["packet"]
    endpoint = visible["endpoint_labels"]
    rag, memory, champion = endpoint["rag"], endpoint["memory"], endpoint["current_champion"]
    samples = visible["sealed_internal_record"]["samples"]
    confidences = [float(sample["confidence"]) for sample in samples]
    bases = Counter(sample["knowledge_basis"] for sample in samples)
    votes = Counter(sample["verdict"] for sample in samples)
    process = visible["original_rag_process"]
    original = relation(row["original_loose_label"], rag=rag, memory=memory)
    counter = relation(row["counter_loose_label"], rag=rag, memory=memory)
    return [
        float(champion == rag),
        votes[memory] / len(samples),
        votes[rag] / len(samples),
        mean(confidences),
        min(confidences),
        max(confidences),
        pstdev(confidences),
        bases["direct_recall"] / len(samples),
        bases["inference"] / len(samples),
        bases["insufficient_knowledge"] / len(samples),
        mean(len(sample["premise_concerns"]) for sample in samples),
        mean(len(sample["decisive_propositions"]) for sample in samples),
        rationale_overlap(samples),
        float(process["confidence"]),
        process["answered_count"] / process["question_count"],
        *original,
        *counter,
    ]


def stress_features(row: dict[str, Any]) -> list[float]:
    visible = row["packet"]
    rag = visible["endpoint_labels"]["rag"]
    memory = visible["endpoint_labels"]["memory"]
    stress = visible["stress_test_record"]
    views = {view["view_type"]: view for view in stress["views"]}
    half_a, half_b = views["half_a"], views["half_b"]
    half_relations = [half_a["endpoint_relation"], half_b["endpoint_relation"]]
    dominant = views.get("dominant_aligned_cluster_removed")
    all_views = list(views.values())
    units = stress["assertion_units"]
    direct = [unit for unit in units if unit["directness"] == "direct"]
    doc_counts = [int(unit["document_count"]) for unit in units]
    total_docs = sum(doc_counts)
    relation_counts = Counter(view["endpoint_relation"] for view in all_views)
    rag_conf = [float(view["confidence"]) for view in all_views if view["verdict"] == rag]
    memory_conf = [float(view["confidence"]) for view in all_views if view["verdict"] == memory]
    return [
        float(half_relations.count("matches_rag") == 2),
        float(half_relations.count("matches_memory") == 2),
        float(set(half_relations) == {"matches_rag", "matches_memory"}),
        half_relations.count("matches_rag") / 2,
        half_relations.count("matches_memory") / 2,
        float(dominant is not None),
        float(dominant is not None and dominant["endpoint_relation"] == "matches_rag"),
        float(dominant is not None and dominant["endpoint_relation"] == "matches_memory"),
        relation_counts["matches_rag"] / len(all_views),
        relation_counts["matches_memory"] / len(all_views),
        sum(view["verdict"] != rag for view in all_views) / len(all_views),
        mean(float(view["confidence"]) for view in all_views),
        min(float(view["confidence"]) for view in all_views),
        max(float(view["confidence"]) for view in all_views),
        (mean(rag_conf) if rag_conf else 0.0) - (mean(memory_conf) if memory_conf else 0.0),
        mean(view["answered_count"] / view["question_count"] for view in all_views),
        min(view["answered_count"] / view["question_count"] for view in all_views),
        float(len(units)),
        len(direct) / len(units),
        max(doc_counts) / total_docs if total_docs else 0.0,
        (
            dominant["removed_document_count"]
            / (dominant["removed_document_count"] + dominant["retained_document_count"])
            if dominant
            else 0.0
        ),
    ]


def llm_features(row: dict[str, Any]) -> list[float]:
    output = row["full_arbiter"]
    return [
        float(output["action"] == "trust_rag"),
        float(output["action"] == "trust_memory"),
        float(output["action"] == "keep_champion"),
        float(output["confidence"]),
        float(output["internal_reliability"] == "reliable"),
        float(output["internal_reliability"] == "uncertain"),
        float(output["rag_stability"] == "robust"),
        float(output["rag_stability"] == "split"),
        float(output["rag_stability"] == "unstable"),
        float(output["influence_concentration"] == "distributed"),
        float(output["influence_concentration"] == "concentrated"),
    ]


def features(row: dict[str, Any], feature_set: str) -> list[float]:
    values = base_features(row)
    if feature_set in {"base_plus_stress", "base_plus_stress_llm"}:
        values += stress_features(row)
    if feature_set == "base_plus_stress_llm":
        values += llm_features(row)
    return values


def estimator() -> Any:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(
        StandardScaler(),
        LogisticRegression(
            C=0.3,
            class_weight="balanced",
            max_iter=3000,
            random_state=20260812,
        ),
    )


def select_threshold(truths: list[int], probabilities: list[float]) -> dict[str, Any]:
    candidates = [value / 100 for value in range(50, 100, 5)] + [1.01]
    records = []
    for threshold in candidates:
        selected = [probability >= threshold for probability in probabilities]
        gains = sum(select and truth for select, truth in zip(selected, truths))
        regressions = sum(select and not truth for select, truth in zip(selected, truths))
        activations = gains + regressions
        records.append(
            {
                "threshold": threshold,
                "gains": gains,
                "regressions": regressions,
                "net": gains - regressions,
                "activations": activations,
                "precision": gains / activations if activations else 1.0,
            }
        )
    # Prefer net benefit, then precision, then fewer interventions and a higher threshold.
    best = max(
        records,
        key=lambda item: (
            item["net"], item["precision"], -item["activations"], item["threshold"]
        ),
    )
    if best["net"] <= 0:
        best = next(item for item in records if item["threshold"] == 1.01)
    return best


def nested_predictions(rows: list[dict[str, Any]], feature_set: str) -> dict[str, Any]:
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedGroupKFold

    x = [features(row, feature_set) for row in rows]
    y = [int(not row["champion_correct"]) for row in rows]
    groups = [row["claim_id"] for row in rows]
    outer = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=20260812)
    probabilities = [0.0] * len(rows)
    predictions = [False] * len(rows)
    fold_records = []
    for fold, (train, test) in enumerate(outer.split(x, y, groups), 1):
        train = list(map(int, train))
        test = list(map(int, test))
        inner_groups = [groups[index] for index in train]
        inner_y = [y[index] for index in train]
        inner_x = [x[index] for index in train]
        inner = StratifiedGroupKFold(n_splits=4, shuffle=True, random_state=20260812 + fold)
        inner_probabilities = [0.0] * len(train)
        for inner_train, inner_test in inner.split(inner_x, inner_y, inner_groups):
            model = estimator()
            model.fit(
                [inner_x[int(index)] for index in inner_train],
                [inner_y[int(index)] for index in inner_train],
            )
            values = model.predict_proba(
                [inner_x[int(index)] for index in inner_test]
            )[:, 1]
            for index, value in zip(inner_test, values):
                inner_probabilities[int(index)] = float(value)
        threshold = select_threshold(inner_y, inner_probabilities)
        model = estimator()
        model.fit([x[index] for index in train], [y[index] for index in train])
        values = model.predict_proba([x[index] for index in test])[:, 1]
        for index, value in zip(test, values):
            probabilities[index] = float(value)
            predictions[index] = float(value) >= threshold["threshold"]
        fold_records.append(
            {
                "fold": fold,
                "test_rows": len(test),
                "test_claims": len({groups[index] for index in test}),
                "inner_selected_threshold": threshold,
            }
        )
    gains = sum(prediction and truth for prediction, truth in zip(predictions, y))
    regressions = sum(prediction and not truth for prediction, truth in zip(predictions, y))
    return {
        "feature_set": feature_set,
        "rows": len(rows),
        "champion_errors": sum(y),
        "roc_auc": roc_auc_score(y, probabilities),
        "activations": sum(predictions),
        "gains": gains,
        "regressions": regressions,
        "net": gains - regressions,
        "precision": gains / sum(predictions) if sum(predictions) else None,
        "recall": gains / sum(y) if sum(y) else None,
        "folds": fold_records,
        "private_predictions": [
            {
                "victim_model_id": row["victim_model_id"],
                "claim_id": row["claim_id"],
                "condition_id": row["condition_id"],
                "champion_wrong": bool(truth),
                "switch": bool(prediction),
                "switch_probability": probability,
            }
            for row, truth, prediction, probability in zip(rows, y, predictions, probabilities)
        ],
    }


def paired(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    gains = sum(row[field + "_correct"] and not row["champion_correct"] for row in rows)
    regressions = sum(not row[field + "_correct"] and row["champion_correct"] for row in rows)
    return {"gains": gains, "regressions": regressions, "net": gains - regressions}


def bootstrap(rows: list[dict[str, Any]], field: str) -> list[float]:
    by_claim: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_claim[row["claim_id"]].append(row)
    claims = sorted(by_claim)
    rng = random.Random(20260812)
    values = []
    for _ in range(10000):
        sampled = rng.choices(claims, k=len(claims))
        deltas = [
            int(row[field + "_correct"]) - int(row["champion_correct"])
            for claim in sampled
            for row in by_claim[claim]
        ]
        values.append(sum(deltas) / len(deltas))
    values.sort()
    return [values[250], values[9749]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base", type=Path,
        default=Path("artifacts/evaluation/counter_retrieval_signal_v2.json"),
    )
    parser.add_argument(
        "--arbiter", type=Path,
        default=Path("artifacts/runs/rag_stress_arbiter/rag_stress_arbiter_v1/private_manifest.json"),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("artifacts/evaluation/rag_stress_rescue_oof_v1.json"),
    )
    args = parser.parse_args()
    base = json.loads(args.base.read_text())
    manifest = json.loads(args.arbiter.read_text())
    if manifest.get("failures") or manifest.get("completed_outputs") != 454:
        raise ValueError("Arbiter manifest is incomplete")
    base_by_id = {identity(row): row for row in base["private_rows"]}
    packets = {}
    arbiters = {}
    descriptors = {}
    for descriptor in manifest["rows"]:
        key = identity(descriptor)
        packet = json.loads(Path(descriptor["packet_path"]).read_text())["visible"]
        output = json.loads(Path(descriptor["output_path"]).read_text())["judgment"]
        packets[(descriptor["variant"], *key)] = packet
        arbiters[(descriptor["variant"], *key)] = output
        descriptors[(descriptor["variant"], *key)] = descriptor
    rows = []
    for key, base_row in base_by_id.items():
        full_key = ("full", *key)
        if full_key not in packets:
            continue
        descriptor = descriptors[full_key]
        champion = descriptor["champion_prediction"]
        other = (
            descriptor["memory_prediction"]
            if champion == descriptor["rag_prediction"]
            else descriptor["rag_prediction"]
        )
        rows.append(
            {
                **base_row,
                "packet": packets[full_key],
                "full_arbiter": arbiters[full_key],
                "control_arbiter": arbiters[("control", *key)],
                "champion_prediction": champion,
                "champion_correct": champion == base_row["gold"],
                "other_prediction": other,
            }
        )
    feature_sets = ("base", "base_plus_stress", "base_plus_stress_llm")
    diagnostics = {name: nested_predictions(rows, name) for name in feature_sets}
    prediction_maps = {
        name: {
            identity(item): item for item in diagnostic["private_predictions"]
        }
        for name, diagnostic in diagnostics.items()
    }
    for row in rows:
        for name in feature_sets:
            selected = prediction_maps[name][identity(row)]["switch"]
            prediction = row["other_prediction"] if selected else row["champion_prediction"]
            row[name + "_prediction"] = prediction
            row[name + "_correct"] = prediction == row["gold"]
    attacked = [row for row in rows if row["condition_id"] != "clean"]
    summaries = {}
    for name in feature_sets:
        summaries[name] = {
            "exclusive_binary": paired(rows, name),
            "attacked_exclusive_binary": paired(attacked, name),
            "claim_cluster_bootstrap95_attacked_accuracy_delta": bootstrap(attacked, name),
            "by_condition": {
                condition: paired(
                    [row for row in rows if row["condition_id"] == condition], name
                )
                for condition in CONDITIONS
            },
            "by_model_attacked": {
                model: paired(
                    [
                        row for row in attacked if row["victim_model_id"] == model
                    ],
                    name,
                )
                for model in sorted({row["victim_model_id"] for row in rows})
            },
        }
    projections = {}
    for name in feature_sets:
        projections[name] = {}
        for condition in CONDITIONS:
            group = base["projected_full_system"]["aggregate"][condition]
            champion_correct = group["systems"]["counter_loose_then_answerability"]["correct"]
            delta = summaries[name]["by_condition"][condition]["net"]
            total = group["rows"]
            projections[name][condition] = {
                "rows": total,
                "correct": champion_correct + delta,
                "accuracy": (champion_correct + delta) / total,
                "champion_correct": champion_correct,
            }
    output = {
        "diagnostic_schema_version": 1,
        "status": "post_label_nested_claim_grouped_method_development",
        "warning": (
            "Feature families and rescue framing were selected after inspecting raw selector "
            "errors. Nested grouped predictions reduce row-level fitting leakage but do not turn "
            "these development claims into confirmation."
        ),
        "method": (
            "Estimate only whether switching away from the selected corroboration champion is a "
            "correction. Attack condition, nominal rate, provenance, gold, and model identity are "
            "not features. Outer and inner cross-validation are grouped by claim."
        ),
        "diagnostics": {
            name: {key: value for key, value in result.items() if key != "private_predictions"}
            for name, result in diagnostics.items()
        },
        "summaries": summaries,
        "projected_full_system": projections,
        "private_predictions": {
            name: result["private_predictions"] for name, result in diagnostics.items()
        },
        "private_rows": rows,
    }
    atomic_json(args.output, output)
    print(
        json.dumps(
            {key: value for key, value in output.items() if key not in {"private_rows", "private_predictions"}},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
