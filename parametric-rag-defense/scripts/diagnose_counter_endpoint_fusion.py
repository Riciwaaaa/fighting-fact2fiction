#!/usr/bin/env python3
"""Claim-grouped OOF diagnostic combining counter evidence and endpoint calibration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json

CONDITIONS = (
    "clean",
    "fact2fiction_p0.001",
    "fact2fiction_p0.0025",
    "fact2fiction_p0.005",
)


def identity(row: dict[str, Any]) -> tuple[str, int, str]:
    return (
        str(row["victim_model_id"]),
        int(row["claim_id"]),
        str(row["condition_id"]),
    )


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    systems = ("rag", "memory", "answerability", "counter", "endpoint_oof", "fusion")
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
            for system in systems
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
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
        "--endpoint-diagnostic",
        type=Path,
        default=Path("artifacts/evaluation/low_rate_aggregation_diagnostic_v1.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluation/counter_endpoint_fusion_oof_v1.json"),
    )
    args = parser.parse_args()
    answerability = json.loads(args.answerability.read_text(encoding="utf-8"))
    counter = json.loads(args.counter.read_text(encoding="utf-8"))
    diagnostic = json.loads(args.endpoint_diagnostic.read_text(encoding="utf-8"))
    counter_by_id = {identity(row): row for row in counter["private_rows"]}
    oof_rows = diagnostic["private_predictions"]["all_pooled"]["endpoint"][
        "logistic_prior"
    ]
    oof_by_id = {identity(row): row for row in oof_rows}

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
        direct_counter_endpoint = None
        if row_id in counter_by_id:
            counter_row = counter_by_id[row_id]
            label = counter_row["counter_loose_label"]
            if label == endpoints["rag"] and label != endpoints["memory"]:
                direct_counter_endpoint = "rag"
            elif label == endpoints["memory"] and label != endpoints["rag"]:
                direct_counter_endpoint = "memory"
            if direct_counter_endpoint:
                counter_endpoint = direct_counter_endpoint
        endpoint_oof = (
            "rag"
            if row_id in oof_by_id and int(oof_by_id[row_id]["prediction"]) == 1
            else "memory"
            if row_id in oof_by_id
            else answerability_endpoint
        )
        fusion_endpoint = direct_counter_endpoint or endpoint_oof
        selected = {
            "rag": "rag",
            "memory": "memory",
            "answerability": answerability_endpoint,
            "counter": counter_endpoint,
            "endpoint_oof": endpoint_oof,
            "fusion": fusion_endpoint,
        }
        row = dict(base)
        for system, endpoint in selected.items():
            row[f"{system}_endpoint"] = endpoint
            row[f"{system}_correct"] = endpoints[endpoint] == base["gold"]
        row["counter_direct_override"] = direct_counter_endpoint
        rows.append(row)

    models = sorted({row["victim_model_id"] for row in rows})
    output = {
        "diagnostic_schema_version": 1,
        "status": "post_label_claim_grouped_oof_exploration",
        "method": (
            "Use direct counter-map endpoint alignment when available; otherwise use the pooled "
            "claim-grouped OOF endpoint-calibration logistic prediction. Model identity, "
            "condition, and poisoning rate are not features."
        ),
        "warning": (
            "The component diagnostics and fusion candidate were selected on the same development "
            "claims. OOF estimates reduce direct fitting leakage but are not confirmation."
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
