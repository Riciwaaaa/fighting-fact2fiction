#!/usr/bin/env python3
"""Evaluate an answerability-aware same-model RAG/memory cascade on cached endpoints."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from build_stage2_packets import internal_lookup
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.labels import canonical_label, deterministic_majority


def exact_paired_pvalue(left_only: int, right_only: int) -> float:
    discordant = left_only + right_only
    if discordant == 0:
        return 1.0
    tail = sum(math.comb(discordant, value) for value in range(min(left_only, right_only) + 1))
    return min(1.0, 2.0 * tail / (2**discordant))


def answerability(samples: list[dict[str, Any]]) -> dict[str, Any]:
    verdict = deterministic_majority(sample["verdict"] for sample in samples)
    binary = verdict in {"Supported", "Refuted"}
    confidences = [float(sample["confidence"]) for sample in samples]
    bases = Counter(sample["knowledge_basis"] for sample in samples)
    return {
        "majority_verdict": verdict,
        "answerable": binary,
        "mean_confidence": sum(confidences) / len(confidences),
        "insufficient_basis_votes": bases["insufficient_knowledge"],
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    systems = ("rag", "memory", "cascade", "oracle")
    correct = {
        system: sum(bool(row[f"{system}_correct"]) for row in rows) for system in systems
    }
    cascade_only_vs_rag = sum(row["cascade_correct"] and not row["rag_correct"] for row in rows)
    rag_only_vs_cascade = sum(row["rag_correct"] and not row["cascade_correct"] for row in rows)
    cascade_only_vs_memory = sum(
        row["cascade_correct"] and not row["memory_correct"] for row in rows
    )
    memory_only_vs_cascade = sum(
        row["memory_correct"] and not row["cascade_correct"] for row in rows
    )
    disagreements = [row for row in rows if row["rag_prediction"] != row["memory_prediction"]]
    return {
        "rows": len(rows),
        "systems": {
            system: {
                "correct": correct[system],
                "accuracy": correct[system] / len(rows) if rows else None,
            }
            for system in systems
        },
        "endpoint_disagreements": len(disagreements),
        "cascade_actions_on_disagreements": dict(
            sorted(Counter(row["cascade_action"] for row in disagreements).items())
        ),
        "cascade_vs_rag": {
            "cascade_only_correct": cascade_only_vs_rag,
            "rag_only_correct": rag_only_vs_cascade,
            "net": cascade_only_vs_rag - rag_only_vs_cascade,
            "exact_p": exact_paired_pvalue(cascade_only_vs_rag, rag_only_vs_cascade),
        },
        "cascade_vs_memory": {
            "cascade_only_correct": cascade_only_vs_memory,
            "memory_only_correct": memory_only_vs_cascade,
            "net": cascade_only_vs_memory - memory_only_vs_cascade,
            "exact_p": exact_paired_pvalue(
                cascade_only_vs_memory, memory_only_vs_cascade
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--eligibility",
        type=Path,
        default=Path("artifacts/evaluation/stage1_rag_v1.2_clean_eligibility.json"),
    )
    parser.add_argument(
        "--rate-curve",
        type=Path,
        default=Path("artifacts/evaluation/stage1_rag_v1.2_combined_rate_curve_v1.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluation/answerability_cascade_v1.json"),
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    dataset = json.loads(Path(config["dataset"]["source"]).read_text(encoding="utf-8"))
    split = json.loads(Path(config["dataset"]["split_manifest"]).read_text(encoding="utf-8"))
    development_ids = {int(value) for value in split["development"]["claim_ids"]}
    eligibility = json.loads(args.eligibility.read_text(encoding="utf-8"))
    rate_curve = json.loads(args.rate_curve.read_text(encoding="utf-8"))
    conditions = [
        "clean", *(f"fact2fiction_p{float(rate):g}" for rate in rate_curve["rates"])
    ]
    models = sorted(rate_curve["models"])
    samples, _ = internal_lookup(
        config,
        Path("artifacts/runs/stage1/development/internal_endpoint"),
        Path(config["cache_root"]),
    )
    answerability_by_model = {
        model: {
            claim_id: answerability(judgments)
            for claim_id, judgments in samples[model].items()
            if claim_id in development_ids
        }
        for model in models
    }
    endpoint_root = (
        Path("artifacts/runs/stage1/development/rag")
        / config["rag_pipeline"]["artifact_namespace"]
        / "endpoints"
    )
    endpoints = {}
    for path in endpoint_root.glob("*/*.json"):
        endpoint = json.loads(path.read_text(encoding="utf-8"))
        task = endpoint["task"]
        identity = (
            str(task["model_id"]),
            int(task["claim_id"]),
            str(task["condition"]["id"]),
        )
        if identity in endpoints:
            raise ValueError(f"Duplicate endpoint: {identity}")
        endpoints[identity] = endpoint

    rows = []
    for model in models:
        eligible = {
            int(value) for value in eligibility["models"][model]["eligible_claim_ids"]
        }
        for condition in conditions:
            scoped_ids = development_ids if condition == "clean" else eligible
            for claim_id in sorted(scoped_ids):
                endpoint = endpoints.get((model, claim_id, condition))
                if endpoint is None:
                    raise ValueError(f"Missing endpoint: {(model, claim_id, condition)}")
                gold = canonical_label(
                    dataset[claim_id]["label"], config["dataset"]["label_mapping"]
                )
                memory = answerability_by_model[model][claim_id]
                rag_prediction = endpoint["judgment"]["verdict"]
                memory_prediction = memory["majority_verdict"]
                cascade_action = "memory" if memory["answerable"] else "rag"
                cascade_prediction = (
                    memory_prediction if cascade_action == "memory" else rag_prediction
                )
                rows.append(
                    {
                        "victim_model_id": model,
                        "claim_id": claim_id,
                        "condition_id": condition,
                        "gold": gold,
                        "rag_prediction": rag_prediction,
                        "memory_prediction": memory_prediction,
                        "cascade_prediction": cascade_prediction,
                        "cascade_action": cascade_action,
                        "memory_answerable": memory["answerable"],
                        "memory_mean_confidence": memory["mean_confidence"],
                        "memory_insufficient_basis_votes": memory[
                            "insufficient_basis_votes"
                        ],
                        "rag_correct": rag_prediction == gold,
                        "memory_correct": memory_prediction == gold,
                        "cascade_correct": cascade_prediction == gold,
                        "oracle_correct": rag_prediction == gold or memory_prediction == gold,
                    }
                )
    by_model_condition = {
        model: {
            condition: summarize(
                [
                    row
                    for row in rows
                    if row["victim_model_id"] == model
                    and row["condition_id"] == condition
                ]
            )
            for condition in conditions
        }
        for model in models
    }
    aggregate = {
        condition: summarize([row for row in rows if row["condition_id"] == condition])
        for condition in conditions
    }
    output = {
        "evaluation_schema_version": 1,
        "status": "post_label_development_diagnostic",
        "rule": (
            "Use the same model's three-sample closed-book majority when it is Supported or "
            "Refuted; otherwise use that model's cached RAG verdict."
        ),
        "interpretation": (
            "The rule was identified after inspecting development behavior and is not frozen or "
            "independently validated. It uses no gold, condition, poison, or model-identity input "
            "at inference time."
        ),
        "conditions": conditions,
        "aggregate": aggregate,
        "by_model_condition": by_model_condition,
        "private_rows": rows,
    }
    atomic_json(args.output, output)
    print(json.dumps({key: value for key, value in output.items() if key != "private_rows"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
