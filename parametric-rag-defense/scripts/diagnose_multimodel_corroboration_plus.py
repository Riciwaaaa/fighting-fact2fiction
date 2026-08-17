#!/usr/bin/env python3
"""Evaluate a cached cross-family panel only after same-model corroboration is unresolved."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from build_stage2_packets import internal_lookup
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.labels import deterministic_majority

CONDITIONS = (
    "clean",
    "fact2fiction_p0.001",
    "fact2fiction_p0.0025",
    "fact2fiction_p0.005",
)
SYSTEMS = ("rag", "memory", "answerability", "counter", "other_two_plus", "all_three_plus")


def identity(row: dict[str, Any]) -> tuple[str, int, str]:
    return (
        str(row["victim_model_id"]),
        int(row["claim_id"]),
        str(row["condition_id"]),
    )


def panel_majority(labels: list[str]) -> str | None:
    votes = Counter(label for label in labels if label in {"Supported", "Refuted"})
    if not votes:
        return None
    leaders = [label for label, count in votes.items() if count == max(votes.values())]
    return leaders[0] if len(leaders) == 1 else None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
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
            for system in SYSTEMS
        },
        "other_two_panel_overrides": sum(
            row["other_two_plus_endpoint"] != row["counter_endpoint"] for row in rows
        ),
        "all_three_panel_overrides": sum(
            row["all_three_plus_endpoint"] != row["counter_endpoint"] for row in rows
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--answerability",
        type=Path,
        default=Path("artifacts/evaluation/answerability_cascade_v1.json"),
    )
    parser.add_argument(
        "--counter",
        type=Path,
        default=Path("artifacts/evaluation/counter_retrieval_signal_v2.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluation/multimodel_corroboration_plus_v1.json"),
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    answerability = json.loads(args.answerability.read_text(encoding="utf-8"))
    counter = json.loads(args.counter.read_text(encoding="utf-8"))
    counter_by_id = {identity(row): row for row in counter["private_rows"]}
    samples, _ = internal_lookup(
        config,
        Path("artifacts/runs/stage1/development/internal_endpoint"),
        Path(config["cache_root"]),
    )
    model_ids = sorted(samples)
    model_claim_labels = {
        model: {
            int(claim_id): deterministic_majority(
                sample["verdict"] for sample in judgments
            )
            for claim_id, judgments in claims.items()
        }
        for model, claims in samples.items()
    }

    rows = []
    for base in answerability["private_rows"]:
        if base["condition_id"] not in CONDITIONS:
            continue
        row_id = identity(base)
        endpoints = {
            "rag": base["rag_prediction"],
            "memory": base["memory_prediction"],
        }
        answerability_endpoint = base["cascade_action"]
        counter_endpoint = answerability_endpoint
        counter_resolved = False
        if row_id in counter_by_id:
            label = counter_by_id[row_id]["counter_loose_label"]
            if label == endpoints["rag"] and label != endpoints["memory"]:
                counter_endpoint = "rag"
                counter_resolved = True
            elif label == endpoints["memory"] and label != endpoints["rag"]:
                counter_endpoint = "memory"
                counter_resolved = True
        victim, claim_id, _ = row_id
        other_label = panel_majority(
            [
                model_claim_labels[model][claim_id]
                for model in model_ids
                if model != victim
            ]
        )
        all_label = panel_majority(
            [model_claim_labels[model][claim_id] for model in model_ids]
        )

        def panel_endpoint(label: str | None) -> str:
            if counter_resolved:
                return counter_endpoint
            if label == endpoints["rag"] and label != endpoints["memory"]:
                return "rag"
            if label == endpoints["memory"] and label != endpoints["rag"]:
                return "memory"
            return counter_endpoint

        selected = {
            "rag": "rag",
            "memory": "memory",
            "answerability": answerability_endpoint,
            "counter": counter_endpoint,
            "other_two_plus": panel_endpoint(other_label),
            "all_three_plus": panel_endpoint(all_label),
        }
        row = dict(base)
        for system, endpoint in selected.items():
            row[f"{system}_endpoint"] = endpoint
            row[f"{system}_correct"] = endpoints[endpoint] == base["gold"]
        row.update(
            {
                "counter_resolved": counter_resolved,
                "other_two_panel_label": other_label,
                "all_three_panel_label": all_label,
            }
        )
        rows.append(row)

    models = sorted({row["victim_model_id"] for row in rows})
    output = {
        "diagnostic_schema_version": 1,
        "status": "post_label_development_plus_variant",
        "method": (
            "Keep the same-model counter-evidence decision when direct. When it is unresolved, "
            "use either a strict agreement of the other two cached model families or the binary "
            "majority of all three families when that label matches exactly one victim endpoint."
        ),
        "warning": (
            "This is a secondary multi-model cost/accuracy diagnostic, not the primary same-model "
            "method and not independent confirmation."
        ),
        "aggregate": {
            condition: summarize([row for row in rows if row["condition_id"] == condition])
            for condition in CONDITIONS
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
                for condition in CONDITIONS
            }
            for model in models
        },
        "private_rows": rows,
    }
    atomic_json(args.output, output)
    print(json.dumps({key: value for key, value in output.items() if key != "private_rows"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
