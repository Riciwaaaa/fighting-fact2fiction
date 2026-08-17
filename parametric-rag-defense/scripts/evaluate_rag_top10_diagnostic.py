#!/usr/bin/env python3
"""Evaluate the opened-confirmation top-10 RAG baseline against frozen systems."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json

SYSTEMS = ("top5_rag", "top10_rag", "memory", "answerability", "proposed", "retrieval_oracle")


def identity_from_endpoint(endpoint: dict[str, Any]) -> tuple[str, int, str]:
    task = endpoint["task"]
    return task["model_id"], int(task["claim_id"]), task["condition"]["id"]


def load_endpoints(root: Path) -> dict[tuple[str, int, str], dict[str, Any]]:
    result = {}
    for path in root.glob("*/*.json"):
        endpoint = json.loads(path.read_text(encoding="utf-8"))
        key = identity_from_endpoint(endpoint)
        if key in result:
            raise ValueError(f"duplicate endpoint: {key}")
        result[key] = endpoint
    return result


def exact_paired_pvalue(left_only: int, right_only: int) -> float:
    discordant = left_only + right_only
    if not discordant:
        return 1.0
    tail = sum(
        math.comb(discordant, value)
        for value in range(min(left_only, right_only) + 1)
    )
    return min(1.0, 2.0 * tail / (2**discordant))


def comparison(rows: list[dict[str, Any]], left: str, right: str) -> dict[str, Any]:
    left_only = sum(
        row[f"{left}_prediction"] == row["gold"]
        and row[f"{right}_prediction"] != row["gold"]
        for row in rows
    )
    right_only = sum(
        row[f"{left}_prediction"] != row["gold"]
        and row[f"{right}_prediction"] == row["gold"]
        for row in rows
    )
    return {
        "left_only_correct": left_only,
        "right_only_correct": right_only,
        "net": left_only - right_only,
        "exact_p": exact_paired_pvalue(left_only, right_only),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "systems": {
            system: {
                "correct": sum(
                    row[f"{system}_prediction"] == row["gold"] for row in rows
                ),
                "accuracy": (
                    sum(row[f"{system}_prediction"] == row["gold"] for row in rows)
                    / len(rows)
                    if rows
                    else None
                ),
            }
            for system in SYSTEMS
        },
        "comparisons": {
            f"top10_vs_{baseline}": comparison(rows, "top10_rag", baseline)
            for baseline in ("top5_rag", "memory", "answerability", "proposed")
        },
        "retrieval": {
            name: {
                "documents": sum(row[f"{name}_retrieved_documents"] for row in rows),
                "poison_documents": sum(
                    row[f"{name}_retrieved_poison_documents"] for row in rows
                ),
                "poison_fraction": (
                    sum(row[f"{name}_retrieved_poison_documents"] for row in rows)
                    / sum(row[f"{name}_retrieved_documents"] for row in rows)
                    if sum(row[f"{name}_retrieved_documents"] for row in rows)
                    else None
                ),
            }
            for name in ("top5", "top10")
        },
        "top5_top10_agreement": (
            sum(row["top5_rag_prediction"] == row["top10_rag_prediction"] for row in rows)
            / len(rows)
            if rows
            else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/rag_top10_confirmation_diagnostic_v1.json"),
    )
    parser.add_argument(
        "--source-results",
        type=Path,
        default=Path(
            "artifacts/evaluation/environment_confirmation_train_v1/"
            "environment_conditioned_results.json"
        ),
    )
    parser.add_argument(
        "--source-endpoints",
        type=Path,
        default=Path(
            "artifacts/runs/environment_confirmation_train_v1/stage1/confirmation/rag/"
            "stage1_train_confirmation_v1/endpoints"
        ),
    )
    parser.add_argument(
        "--top10-endpoints",
        type=Path,
        default=Path(
            "artifacts/runs/rag_top10_confirmation_v1/stage1/confirmation/rag/"
            "rag_top10_confirmation_v1/endpoints"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "artifacts/evaluation/rag_top10_confirmation_v1/paired_results.json"
        ),
    )
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    if config.get("status") != "frozen_before_rag_top10_diagnostic_inference":
        raise ValueError("top-10 diagnostic configuration is not frozen")
    source = json.loads(args.source_results.read_text(encoding="utf-8"))
    top5_endpoints = load_endpoints(args.source_endpoints)
    top10_endpoints = load_endpoints(args.top10_endpoints)
    expected = {
        (row["victim_model_id"], int(row["claim_id"]), row["condition_id"])
        for row in source["private_rows"]
    }
    missing = sorted(expected - set(top10_endpoints))
    unexpected = sorted(set(top10_endpoints) - expected)
    if missing or unexpected:
        raise ValueError(
            f"top-10 endpoint scope mismatch: missing={len(missing)} unexpected={len(unexpected)}"
        )

    rows = []
    for original in source["private_rows"]:
        key = (
            original["victim_model_id"],
            int(original["claim_id"]),
            original["condition_id"],
        )
        top5 = top5_endpoints[key]
        top10 = top10_endpoints[key]
        if top10["provenance"].get("retrieval_top_k") != 10:
            raise ValueError(f"endpoint is not top-10: {key}")
        top5_prediction = original["rag_prediction"]
        top10_prediction = top10["judgment"]["verdict"]
        rows.append(
            {
                "victim_model_id": key[0],
                "claim_id": key[1],
                "condition_id": key[2],
                "gold": original["gold"],
                "top5_rag_prediction": top5_prediction,
                "top10_rag_prediction": top10_prediction,
                "memory_prediction": original["memory_prediction"],
                "answerability_prediction": original["answerability_prediction"],
                "proposed_prediction": original["proposed_prediction"],
                "retrieval_oracle_prediction": (
                    top10_prediction
                    if top10_prediction == original["gold"]
                    else top5_prediction
                ),
                "top5_retrieved_documents": int(
                    top5["audit"]["retrieved_documents_total"]
                ),
                "top5_retrieved_poison_documents": int(
                    top5["audit"]["retrieved_poison_documents"]
                ),
                "top10_retrieved_documents": int(
                    top10["audit"]["retrieved_documents_total"]
                ),
                "top10_retrieved_poison_documents": int(
                    top10["audit"]["retrieved_poison_documents"]
                ),
            }
        )

    conditions = sorted({row["condition_id"] for row in rows})
    models = sorted({row["victim_model_id"] for row in rows})
    attacked = [row for row in rows if row["condition_id"] != "clean"]
    result = {
        "evaluation_schema_version": 1,
        "experiment_id": "rag_top10_confirmation_v1",
        "status": "opened_confirmation_diagnostic_not_independent_validation",
        "retrieval_budget": {
            "standard_top_k_per_subquestion": 5,
            "diagnostic_top_k_per_subquestion": 10,
            "question_count": 10,
        },
        "scope_audit": {
            "expected_rows": len(expected),
            "completed_rows": len(rows),
            "missing": len(missing),
            "unexpected": len(unexpected),
            "closed_book_used_by_top10_endpoint": False,
            "original_top5_eligibility_reused": True,
            "original_questions_and_poison_corpora_reused": True,
        },
        "aggregate": {
            condition: summarize(
                [row for row in rows if row["condition_id"] == condition]
            )
            for condition in conditions
        },
        "attacked_pooled": summarize(attacked),
        "clean_pooled": summarize(
            [row for row in rows if row["condition_id"] == "clean"]
        ),
        "attacked_by_model": {
            model: summarize(
                [row for row in attacked if row["victim_model_id"] == model]
            )
            for model in models
        },
        "by_model_condition": {
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
        },
        "private_rows": rows,
    }
    atomic_json(args.output, result)
    compact = {
        "status": result["status"],
        "scope_audit": result["scope_audit"],
        "clean": result["clean_pooled"],
        "attacked": result["attacked_pooled"],
        "by_condition": result["aggregate"],
        "by_model": result["attacked_by_model"],
    }
    print(json.dumps(compact, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
