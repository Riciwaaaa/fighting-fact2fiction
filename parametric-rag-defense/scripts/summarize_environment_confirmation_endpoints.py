#!/usr/bin/env python3
"""Join confirmation gold after collection and summarize RAG/memory endpoints."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from build_stage2_packets import internal_lookup
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.labels import canonical_label, deterministic_majority
from parametric_rag_defense.matrix import select_tier_conditions


def exact_paired_pvalue(left_only: int, right_only: int) -> float:
    discordant = left_only + right_only
    if not discordant:
        return 1.0
    tail = sum(
        math.comb(discordant, value)
        for value in range(min(left_only, right_only) + 1)
    )
    return min(1.0, 2.0 * tail / (2**discordant))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    systems = ("rag", "memory", "answerability", "oracle")
    result = {
        "rows": len(rows),
        "endpoint_disagreements": sum(
            row["rag_prediction"] != row["memory_prediction"] for row in rows
        ),
        "memory_answerable": sum(row["memory_answerable"] for row in rows),
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
            for system in systems
        },
    }
    for left, right in (("answerability", "rag"), ("answerability", "memory")):
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
        result[f"{left}_vs_{right}"] = {
            "left_only_correct": left_only,
            "right_only_correct": right_only,
            "net": left_only - right_only,
            "exact_p": exact_paired_pvalue(left_only, right_only),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/stage1_environment_confirmation_train_v1.json"),
    )
    parser.add_argument("--tier", default="fresh_confirmation_curve")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "artifacts/evaluation/environment_confirmation_train_v1/endpoint_summary.json"
        ),
    )
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    active_split = config["dataset"].get("active_split", "development")
    split = json.loads(Path(config["dataset"]["split_manifest"]).read_text(encoding="utf-8"))
    claim_ids = {int(value) for value in split[active_split]["claim_ids"]}
    dataset = json.loads(Path(config["dataset"]["source"]).read_text(encoding="utf-8"))
    conditions = [value["id"] for value in select_tier_conditions(config, args.tier)]
    models = sorted(
        model["id"]
        for model in config["models"]
        if model.get("enabled", True) and "rag_victim" in model["roles"]
    )
    samples, _ = internal_lookup(
        config,
        Path(config["run_root"]) / active_split / "internal_endpoint",
        Path(config["cache_root"]),
    )
    memory: dict[str, dict[int, dict[str, Any]]] = {}
    for model in models:
        memory[model] = {}
        for claim_id in claim_ids:
            judgments = samples[model][claim_id]
            majority = deterministic_majority(value["verdict"] for value in judgments)
            bases = Counter(value["knowledge_basis"] for value in judgments)
            memory[model][claim_id] = {
                "prediction": majority,
                "answerable": majority in {"Supported", "Refuted"},
                "insufficient_basis_votes": bases["insufficient_knowledge"],
            }

    endpoint_root = (
        Path(config["run_root"])
        / active_split
        / "rag"
        / config["rag_pipeline"]["artifact_namespace"]
        / "endpoints"
    )
    endpoints: dict[tuple[str, int, str], dict[str, Any]] = {}
    for path in endpoint_root.glob("*/*.json"):
        endpoint = json.loads(path.read_text(encoding="utf-8"))
        task = endpoint["task"]
        identity = (
            str(task["model_id"]),
            int(task["claim_id"]),
            str(task["condition"]["id"]),
        )
        if identity in endpoints:
            raise ValueError(f"duplicate endpoint {identity}")
        endpoints[identity] = endpoint

    clean_ids: dict[str, set[int]] = {}
    eligibility = json.loads(
        (
            Path(config["evaluation_root"])
            / f"{config['rag_pipeline']['artifact_namespace']}_clean_eligibility.json"
        ).read_text(encoding="utf-8")
    )
    for model in models:
        clean_ids[model] = {
            int(value) for value in eligibility["models"][model]["eligible_claim_ids"]
        }

    rows = []
    for model in models:
        for condition in conditions:
            scope = claim_ids if condition == "clean" else clean_ids[model]
            for claim_id in sorted(scope):
                endpoint = endpoints.get((model, claim_id, condition))
                if endpoint is None:
                    raise ValueError(f"missing endpoint {(model, claim_id, condition)}")
                gold = canonical_label(
                    dataset[claim_id]["label"], config["dataset"].get("label_mapping", {})
                )
                internal = memory[model][claim_id]
                rag = endpoint["judgment"]["verdict"]
                anchor = internal["prediction"]
                answerability = anchor if internal["answerable"] else rag
                oracle = rag if rag == gold else anchor
                rows.append(
                    {
                        "victim_model_id": model,
                        "claim_id": claim_id,
                        "condition_id": condition,
                        "gold": gold,
                        "rag_prediction": rag,
                        "memory_prediction": anchor,
                        "answerability_prediction": answerability,
                        "oracle_prediction": oracle,
                        "memory_answerable": internal["answerable"],
                        "memory_insufficient_basis_votes": internal[
                            "insufficient_basis_votes"
                        ],
                    }
                )

    attacked = [row for row in rows if row["condition_id"] != "clean"]
    output = {
        "evaluation_schema_version": 1,
        "experiment_id": "environment_confirmation_train_v1",
        "status": "fresh_confirmation_gold_joined_after_endpoint_collection",
        "conditions": conditions,
        "aggregate": {
            condition: summarize(
                [row for row in rows if row["condition_id"] == condition]
            )
            for condition in conditions
        },
        "attacked_pooled": summarize(attacked),
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
