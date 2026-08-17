#!/usr/bin/env python3
"""Measure poison exposure versus poison selection in existing disagreement traces."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.query_trace import audit_question_trace, safe_ratio


def row_key(row: dict[str, Any]) -> tuple[str, int, str]:
    return row["victim_model_id"], int(row["claim_id"]), row["condition_id"]


def summarize(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = list(rows)
    rag_wrong = [row for row in values if not row["rag_correct"]]
    rag_correct = [row for row in values if row["rag_correct"]]
    wrong_selected = sum(row["poison_selected_row"] for row in rag_wrong)
    correct_selected = sum(row["poison_selected_row"] for row in rag_correct)
    wrong_selected_rate = safe_ratio(wrong_selected, len(rag_wrong))
    correct_selected_rate = safe_ratio(correct_selected, len(rag_correct))
    risk_ratio = (
        wrong_selected_rate / correct_selected_rate
        if wrong_selected_rate is not None and correct_selected_rate
        else None
    )
    return {
        "rows": len(values),
        "distinct_claims": len({int(row["claim_id"]) for row in values}),
        "distinct_model_claim_cases": len(
            {(row["victim_model_id"], int(row["claim_id"])) for row in values}
        ),
        "rag_correct_rows": len(rag_correct),
        "rag_wrong_rows": len(rag_wrong),
        "poison_exposed_rows": sum(row["poison_exposed_row"] for row in values),
        "poison_selected_rows": sum(row["poison_selected_row"] for row in values),
        "poison_exposed_questions": sum(row["poison_exposed_question_count"] for row in values),
        "poison_selected_answers": sum(row["poison_selected_answer_count"] for row in values),
        "answered_questions": sum(row["answered_question_count"] for row in values),
        "rag_wrong_poison_exposed_rows": sum(row["poison_exposed_row"] for row in rag_wrong),
        "rag_wrong_poison_selected_rows": wrong_selected,
        "rag_correct_poison_exposed_rows": sum(row["poison_exposed_row"] for row in rag_correct),
        "rag_correct_poison_selected_rows": correct_selected,
        "selected_poison_rate_given_rag_wrong": wrong_selected_rate,
        "selected_poison_rate_given_rag_correct": correct_selected_rate,
        "wrong_vs_correct_selected_poison_risk_ratio": risk_ratio,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=Path(
            "artifacts/runs/counter_retrieval/counter_retrieval_signal_v2/private_manifest.json"
        ),
    )
    parser.add_argument(
        "--source-evaluation",
        type=Path,
        default=Path("artifacts/evaluation/counter_retrieval_signal_v2.json"),
    )
    parser.add_argument(
        "--trace-root",
        type=Path,
        default=Path(
            "artifacts/runs/stage1/development/rag/stage1_rag_v1.2/private_traces"
        ),
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("configs/query_aligned_trace_feasibility_v1.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluation/query_aligned_trace_feasibility_v1.json"),
    )
    args = parser.parse_args()

    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    manifest = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    evaluation = json.loads(args.source_evaluation.read_text(encoding="utf-8"))
    labels = {row_key(row): row for row in evaluation["private_rows"]}
    if len(labels) != len(evaluation["private_rows"]):
        raise ValueError("Evaluation rows are not unique")

    rows: list[dict[str, Any]] = []
    for descriptor in manifest["rows"]:
        key = row_key(descriptor)
        label = labels.get(key)
        if label is None:
            raise ValueError(f"Missing evaluation row: {key}")
        task_key = descriptor["rag_task_key"]
        trace_path = args.trace_root / task_key[:2] / f"{task_key}.json"
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        if trace.get("task_key") != task_key:
            raise ValueError(f"Trace task-key mismatch: {trace_path}")
        audit = audit_question_trace(trace)
        rows.append(
            {
                "victim_model_id": descriptor["victim_model_id"],
                "claim_id": int(descriptor["claim_id"]),
                "condition_id": descriptor["condition_id"],
                "rag_task_key": task_key,
                "rag_prediction": label["rag_prediction"],
                "rag_correct": bool(label["rag_correct"]),
                "memory_prediction": label["memory_prediction"],
                "memory_correct": bool(label["memory_correct"]),
                "cascade_prediction": label["cascade_prediction"],
                "cascade_correct": bool(label["cascade_correct"]),
                **audit,
            }
        )

    if len(rows) != len(manifest["rows"]):
        raise ValueError("Not all manifest rows were analyzed")
    attacked = [row for row in rows if row["condition_id"] != "clean"]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    model_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    model_condition_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["condition_id"]].append(row)
        model_groups[row["victim_model_id"]].append(row)
        model_condition_groups[f'{row["victim_model_id"]}::{row["condition_id"]}'].append(row)

    gate = protocol["follow_up_gate"]
    attacked_wrong_selected = [
        row for row in attacked if not row["rag_correct"] and row["poison_selected_row"]
    ]
    victim_count = len({row["victim_model_id"] for row in attacked_wrong_selected})
    attacked_summary = summarize(attacked)
    risk_ratio = attacked_summary["wrong_vs_correct_selected_poison_risk_ratio"]
    gate_checks = {
        "enough_selected_poison_errors": len(attacked_wrong_selected)
        >= gate["minimum_attacked_rag_error_rows_with_selected_poison"],
        "enough_victim_models": victim_count
        >= gate["minimum_victim_models_with_selected_poison_errors"],
        "enough_wrong_correct_enrichment": risk_ratio is not None
        and risk_ratio >= gate["minimum_wrong_vs_correct_selected_poison_risk_ratio"],
    }
    result = {
        "evaluation_schema_version": 1,
        "experiment_id": protocol["experiment_id"],
        "status": "complete_development_trace_diagnostic",
        "protocol_path": str(args.protocol),
        "source_manifest": str(args.source_manifest),
        "source_evaluation": str(args.source_evaluation),
        "aggregate": summarize(rows),
        "attacked_aggregate": attacked_summary,
        "by_condition": {key: summarize(value) for key, value in sorted(groups.items())},
        "by_model": {key: summarize(value) for key, value in sorted(model_groups.items())},
        "by_model_condition": {
            key: summarize(value) for key, value in sorted(model_condition_groups.items())
        },
        "follow_up_gate": {
            "checks": gate_checks,
            "passed": all(gate_checks.values()),
            "attacked_rag_error_rows_with_selected_poison": len(attacked_wrong_selected),
            "victim_models_with_selected_poison_errors": victim_count,
            "attacked_wrong_vs_correct_selected_poison_risk_ratio": risk_ratio,
        },
        "private_rows": rows,
        "interpretation_boundary": (
            "Selected poison entered the final judge record but is not assumed causal. "
            "Poison provenance is evaluation-only and cannot be used by a defense."
        ),
    }
    atomic_json(args.output, result)
    print(json.dumps({key: value for key, value in result.items() if key != "private_rows"}, indent=2))


if __name__ == "__main__":
    main()
