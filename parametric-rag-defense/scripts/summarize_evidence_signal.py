#!/usr/bin/env python3
"""Join development labels after audit and measure passage-map endpoint-selection signal."""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.labels import canonical_label

CONDITIONS = (
    "clean",
    "fact2fiction_p0.001",
    "fact2fiction_p0.0025",
    "fact2fiction_p0.005",
)

POLICIES = (
    ("loose_memory_default", "memory", False),
    ("strict_memory_default", "memory", True),
    ("loose_rag_default", "retrieval", False),
    ("strict_rag_default", "retrieval", True),
)


def safe_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def evidence_label(judgment: dict[str, Any], *, strict: bool = False) -> str | None:
    overall = judgment["overall_assessment"]
    direction = overall["direction"]
    if direction not in {"supports", "refutes"}:
        return None
    if strict:
        aligned = (
            overall["direct_support_cluster_ids"]
            if direction == "supports"
            else overall["direct_refutation_cluster_ids"]
        )
        opposing = (
            overall["direct_refutation_cluster_ids"]
            if direction == "supports"
            else overall["direct_support_cluster_ids"]
        )
        if not aligned or opposing or overall["evidence_conflict"]:
            return None
    return "Supported" if direction == "supports" else "Refuted"


def choose_endpoint(
    row: dict[str, Any], *, default: str, strict: bool = False
) -> str:
    label = evidence_label(row["judgment"], strict=strict)
    if label == row["retrieval_prediction"] and label != row["memory_prediction"]:
        return "retrieval"
    if label == row["memory_prediction"] and label != row["retrieval_prediction"]:
        return "memory"
    return default


def selected_prediction(row: dict[str, Any], endpoint: str) -> str:
    return row[f"{endpoint}_prediction"]


def row_features(row: dict[str, Any], *, include_endpoint_alignment: bool) -> list[float]:
    packet = row["packet"]["visible"]
    judgment = row["judgment"]
    assessments = judgment["passage_assessments"]
    clusters = judgment["content_clusters"]
    overall = judgment["overall_assessment"]
    passage_count = len(assessments)
    occurrence_count = sum(
        len(question["passage_ids"]) for question in packet["retrieval_questions"]
    )
    stance_counts = Counter(item["stance"] for item in assessments)
    direct_counts = Counter(
        item["stance"] for item in assessments if item["directness"] == "direct"
    )
    quality_counts = Counter(item["quality_concern"] for item in assessments)
    cluster_stances = Counter(item["stance"] for item in clusters)
    direction = overall["direction"]
    features = [
        float(passage_count),
        float(occurrence_count),
        safe_rate(occurrence_count - passage_count, occurrence_count) or 0.0,
        float(len(clusters)),
        safe_rate(len({p for c in clusters for p in c["passage_ids"]}), passage_count)
        or 0.0,
        float(len(overall["direct_support_cluster_ids"])),
        float(len(overall["direct_refutation_cluster_ids"])),
        float(overall["evidence_conflict"]),
    ]
    features.extend(
        safe_rate(stance_counts[name], passage_count) or 0.0
        for name in ("supports", "refutes", "context", "irrelevant", "ambiguous")
    )
    features.extend(
        safe_rate(direct_counts[name], passage_count) or 0.0
        for name in ("supports", "refutes")
    )
    features.extend(
        safe_rate(cluster_stances[name], len(clusters)) or 0.0
        for name in ("supports", "refutes", "context", "irrelevant", "ambiguous")
    )
    features.extend(
        safe_rate(quality_counts[name], passage_count) or 0.0
        for name in (
            "none",
            "unsupported_assertion",
            "opinion_or_commentary",
            "internal_inconsistency",
            "off_topic",
            "insufficient_context",
        )
    )
    features.extend(float(direction == name) for name in ("supports", "refutes", "mixed", "insufficient"))
    if include_endpoint_alignment:
        loose_label = evidence_label(judgment)
        strict_label = evidence_label(judgment, strict=True)
        features.extend(
            [
                float(loose_label == row["retrieval_prediction"]),
                float(loose_label == row["memory_prediction"]),
                float(strict_label == row["retrieval_prediction"]),
                float(strict_label == row["memory_prediction"]),
            ]
        )
    return features


def grouped_probe(rows: list[dict[str, Any]], *, include_endpoint_alignment: bool) -> dict[str, Any]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, balanced_accuracy_score, roc_auc_score
    from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    exclusive = [row for row in rows if row["rag_correct"] != row["memory_correct"]]
    y = [int(row["rag_correct"]) for row in exclusive]
    groups = [row["claim_id"] for row in exclusive]
    if len(exclusive) < 20 or min(Counter(y).values(), default=0) < 5:
        return {"status": "insufficient_rows", "rows": len(exclusive), "classes": dict(Counter(y))}
    x = [
        row_features(row, include_endpoint_alignment=include_endpoint_alignment)
        for row in exclusive
    ]
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=20260811)
    estimator = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000, random_state=20260811),
    )
    probabilities = cross_val_predict(
        estimator, x, y, groups=groups, cv=splitter, method="predict_proba"
    )[:, 1]
    predictions = [int(value >= 0.5) for value in probabilities]
    rag_cases = sum(y)
    memory_cases = len(y) - rag_cases
    constant_prediction = int(rag_cases >= memory_cases)
    constant_accuracy = max(rag_cases, memory_cases) / len(y)
    deltas_by_claim: dict[int, list[int]] = defaultdict(list)
    for truth, prediction, claim_id in zip(y, predictions, groups):
        deltas_by_claim[claim_id].append(
            int(prediction == truth) - int(constant_prediction == truth)
        )
    rng = random.Random(20260811)
    unique_claims = sorted(deltas_by_claim)
    bootstrap_deltas: list[float] = []
    for _ in range(5000):
        sampled = rng.choices(unique_claims, k=len(unique_claims))
        values = [value for claim_id in sampled for value in deltas_by_claim[claim_id]]
        bootstrap_deltas.append(sum(values) / len(values))
    bootstrap_deltas.sort()
    return {
        "status": "complete",
        "rows": len(exclusive),
        "unique_claims": len(set(groups)),
        "rag_correct_cases": rag_cases,
        "memory_correct_cases": memory_cases,
        "stronger_constant_endpoint": "rag" if constant_prediction else "memory",
        "stronger_constant_accuracy": constant_accuracy,
        "grouped_cv_accuracy": accuracy_score(y, predictions),
        "grouped_cv_accuracy_delta_vs_constant": (
            accuracy_score(y, predictions) - constant_accuracy
        ),
        "claim_cluster_bootstrap95_delta_vs_constant": [
            bootstrap_deltas[int(0.025 * len(bootstrap_deltas))],
            bootstrap_deltas[int(0.975 * len(bootstrap_deltas)) - 1],
        ],
        "grouped_cv_balanced_accuracy": balanced_accuracy_score(y, predictions),
        "grouped_cv_roc_auc": roc_auc_score(y, probabilities),
    }


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "rows": len(rows),
        "rag_correct": sum(row["rag_correct"] for row in rows),
        "memory_correct": sum(row["memory_correct"] for row in rows),
        "both_wrong": sum(not row["rag_correct"] and not row["memory_correct"] for row in rows),
    }
    for policy, default, strict in POLICIES:
        endpoints = [choose_endpoint(row, default=default, strict=strict) for row in rows]
        correct = sum(
            selected_prediction(row, endpoint) == row["gold"]
            for row, endpoint in zip(rows, endpoints)
        )
        switched = [
            row for row, endpoint in zip(rows, endpoints) if endpoint != default
        ]
        default_correct = result[
            "rag_correct" if default == "retrieval" else "memory_correct"
        ]
        result[policy] = {
            "correct": correct,
            "accuracy": safe_rate(correct, len(rows)),
            "retrieval_choices": sum(endpoint == "retrieval" for endpoint in endpoints),
            "memory_choices": sum(endpoint == "memory" for endpoint in endpoints),
            "switches_from_default": len(switched),
            "unique_switched_claims": len({row["claim_id"] for row in switched}),
            "switched_claim_ids": sorted({row["claim_id"] for row in switched}),
            "gains": sum(
                selected_prediction(
                    row, "memory" if default == "retrieval" else "retrieval"
                )
                == row["gold"]
                and selected_prediction(row, default) != row["gold"]
                for row in switched
            ),
            "regressions": sum(
                selected_prediction(row, default) == row["gold"]
                and selected_prediction(
                    row, "memory" if default == "retrieval" else "retrieval"
                )
                != row["gold"]
                for row in switched
            ),
            "net_correct_change_vs_default": correct - default_correct,
        }
    directions = Counter(row["judgment"]["overall_assessment"]["direction"] for row in rows)
    result["evidence_directions"] = dict(sorted(directions.items()))
    result["loose_direction_coverage"] = safe_rate(
        sum(evidence_label(row["judgment"]) is not None for row in rows), len(rows)
    )
    result["strict_direction_coverage"] = safe_rate(
        sum(evidence_label(row["judgment"], strict=True) is not None for row in rows), len(rows)
    )
    return result


def endpoint_counts(
    rate_curve: dict[str, Any], *, condition: str, model: str | None = None
) -> dict[str, int]:
    """Return exact full-scope endpoint counts for a model/condition cell."""
    if condition == "clean":
        model_rows = (
            [rate_curve["models"][model]]
            if model is not None
            else list(rate_curve["models"].values())
        )
        total = sum(item["full_development"]["clean_rag_completed"] for item in model_rows)
        rag_correct = sum(
            round(
                item["full_development"]["clean_rag_accuracy"]
                * item["full_development"]["clean_rag_completed"]
            )
            for item in model_rows
        )
        memory_correct = sum(
            round(
                item["full_development"]["model_only_accuracy"]
                * item["full_development"]["clean_rag_completed"]
            )
            for item in model_rows
        )
    else:
        scope = (
            rate_curve["models"][model]["levels"][condition]
            if model is not None
            else rate_curve["aggregate"]["levels"][condition]
        )
        outcomes = scope["endpoint_outcomes"]
        total = scope["paired_claims"]
        rag_correct = outcomes["both_correct"] + outcomes["rag_only_correct"]
        memory_correct = outcomes["both_correct"] + outcomes["internal_only_correct"]
    return {
        "rows": total,
        "rag_correct": rag_correct,
        "memory_correct": memory_correct,
    }


def project_full_system(
    disagreement_summary: dict[str, Any], endpoint_baselines: dict[str, int]
) -> dict[str, Any]:
    """Pass agreements through and apply each diagnostic only to disagreements."""
    total = endpoint_baselines["rows"]
    result: dict[str, Any] = {
        "rows": total,
        "rag": {
            "correct": endpoint_baselines["rag_correct"],
            "accuracy": safe_rate(endpoint_baselines["rag_correct"], total),
        },
        "memory": {
            "correct": endpoint_baselines["memory_correct"],
            "accuracy": safe_rate(endpoint_baselines["memory_correct"], total),
        },
    }
    for policy, default, _ in POLICIES:
        baseline_key = "rag_correct" if default == "retrieval" else "memory_correct"
        correct = (
            endpoint_baselines[baseline_key]
            + disagreement_summary[policy]["net_correct_change_vs_default"]
        )
        result[policy] = {
            "correct": correct,
            "accuracy": safe_rate(correct, total),
            "net_correct_change_vs_default": disagreement_summary[policy][
                "net_correct_change_vs_default"
            ],
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("artifacts/runs/evidence_signal/evidence_signal_v1"),
    )
    parser.add_argument("--dataset", type=Path, default=Path("../fighting-fact2fiction-main/DEFAME/data/AVeriTeC/dev.json"))
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/evaluation/evidence_signal_v1.json")
    )
    parser.add_argument(
        "--rate-curve",
        type=Path,
        default=Path(
            "artifacts/evaluation/stage1_rag_v1.2_combined_rate_curve_v1.json"
        ),
    )
    args = parser.parse_args()
    audit = json.loads((args.run_root / "audit.json").read_text(encoding="utf-8"))
    if audit.get("status") != "passed":
        raise ValueError("Evidence signal must pass pre-label audit before evaluation")
    manifest = json.loads((args.run_root / "private_manifest.json").read_text(encoding="utf-8"))
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    rate_curve = json.loads(args.rate_curve.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    namespace_root = Path("artifacts/runs/stage1/development/rag/stage1_rag_v1.2")
    for descriptor in manifest["rows"]:
        packet = json.loads(Path(descriptor["packet_path"]).read_text(encoding="utf-8"))
        output = json.loads(Path(descriptor["output_path"]).read_text(encoding="utf-8"))
        claim_id = int(descriptor["claim_id"])
        gold = canonical_label(
            dataset[claim_id]["label"],
            {"Conflicting Evidence/Cherrypicking": "Conflicting Evidence"},
        )
        trace_path = (
            namespace_root
            / "private_traces"
            / descriptor["rag_task_key"][:2]
            / f"{descriptor['rag_task_key']}.json"
        )
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        retrieved = [item for question in trace["retrievals"] for item in question]
        row = {
            "claim_id": claim_id,
            "victim_model_id": descriptor["victim_model_id"],
            "condition_id": descriptor["condition_id"],
            "gold": gold,
            "retrieval_prediction": descriptor["retrieval_prediction"],
            "memory_prediction": descriptor["memory_prediction"],
            "rag_correct": descriptor["retrieval_prediction"] == gold,
            "memory_correct": descriptor["memory_prediction"] == gold,
            "packet": packet,
            "judgment": output["judgment"],
            "private_retrieved_count": len(retrieved),
            "private_poison_count": sum(bool(item["is_poison"]) for item in retrieved),
        }
        rows.append(row)

    by_condition = {
        condition: summarize_rows([row for row in rows if row["condition_id"] == condition])
        for condition in CONDITIONS
    }
    by_model_condition = {
        model: {
            condition: summarize_rows(
                [
                    row
                    for row in rows
                    if row["victim_model_id"] == model and row["condition_id"] == condition
                ]
            )
            for condition in CONDITIONS
        }
        for model in sorted({row["victim_model_id"] for row in rows})
    }
    projected_full_system = {
        "interpretation": (
            "Exact endpoint totals with agreements passed through unchanged and each fixed "
            "diagnostic policy applied only to endpoint disagreements."
        ),
        "by_condition": {
            condition: project_full_system(
                by_condition[condition],
                endpoint_counts(rate_curve, condition=condition),
            )
            for condition in CONDITIONS
        },
        "by_model_condition": {
            model: {
                condition: project_full_system(
                    by_model_condition[model][condition],
                    endpoint_counts(rate_curve, condition=condition, model=model),
                )
                for condition in CONDITIONS
            }
            for model in by_model_condition
        },
    }
    attacked = [row for row in rows if row["condition_id"] != "clean"]
    poison_bins: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in attacked:
        count = row["private_poison_count"]
        name = "0" if count == 0 else "1" if count == 1 else "2" if count == 2 else "3+"
        poison_bins[name].append(row)
    output = {
        "evaluation_schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "interpretation": (
            "Development-only diagnostic. Fixed direction/default policies and grouped probes are "
            "signal measurements, not proposed defenses or independent validation results."
        ),
        "all_disagreements": summarize_rows(rows),
        "attacked_disagreements": summarize_rows(attacked),
        "clean_disagreements": summarize_rows(
            [row for row in rows if row["condition_id"] == "clean"]
        ),
        "by_condition": by_condition,
        "by_model_condition": by_model_condition,
        "projected_full_system": projected_full_system,
        "grouped_probes": {
            "attacked_structure_only": grouped_probe(
                attacked, include_endpoint_alignment=False
            ),
            "attacked_plus_endpoint_alignment": grouped_probe(
                attacked, include_endpoint_alignment=True
            ),
            "all_structure_only": grouped_probe(rows, include_endpoint_alignment=False),
            "all_plus_endpoint_alignment": grouped_probe(
                rows, include_endpoint_alignment=True
            ),
        },
        "private_poison_exposure_diagnostic": {
            name: summarize_rows(bin_rows) for name, bin_rows in sorted(poison_bins.items())
        },
        "private_rows": [
            {
                key: value
                for key, value in row.items()
                if key not in {"packet", "judgment"}
            }
            | {
                "evidence_direction": row["judgment"]["overall_assessment"]["direction"],
                "loose_evidence_label": evidence_label(row["judgment"]),
                "strict_evidence_label": evidence_label(row["judgment"], strict=True),
                "passage_count": len(row["judgment"]["passage_assessments"]),
                "content_cluster_count": len(row["judgment"]["content_clusters"]),
            }
            for row in rows
        ],
    }
    atomic_json(args.output, output)
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
