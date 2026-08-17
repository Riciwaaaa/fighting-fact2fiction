#!/usr/bin/env python3
"""Evaluate the frozen query-aligned conflict map and its intervention gate."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.query_aligned_internal import (
    eligible_conflict_indices,
    suspect_document_ids,
)
from parametric_rag_defense.query_trace import safe_ratio


def row_key(row: dict[str, Any]) -> tuple[str, int, str]:
    return row["victim_model_id"], int(row["claim_id"]), row["condition_id"]


def summarize(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = list(rows)
    flagged = [row for row in values if row["conflict_flag"]]
    unflagged = [row for row in values if not row["conflict_flag"]]
    flagged_errors = sum(not row["rag_correct"] for row in flagged)
    unflagged_errors = sum(not row["rag_correct"] for row in unflagged)
    flagged_error_rate = safe_ratio(flagged_errors, len(flagged))
    unflagged_error_rate = safe_ratio(unflagged_errors, len(unflagged))
    risk_ratio = (
        flagged_error_rate / unflagged_error_rate
        if flagged_error_rate is not None and unflagged_error_rate
        else None
    )
    poison_selected_rows = [row for row in values if row["poison_selected_row"]]
    localized_poison_rows = [row for row in values if row["suspect_poison_row"]]
    return {
        "rows": len(values),
        "distinct_claims": len({row["claim_id"] for row in values}),
        "rag_wrong_rows": sum(not row["rag_correct"] for row in values),
        "conflict_flagged_rows": len(flagged),
        "conflict_questions": sum(row["eligible_conflict_count"] for row in values),
        "stable_internal_questions": sum(row["stable_internal_question_count"] for row in values),
        "flagged_rag_wrong_rows": flagged_errors,
        "flagged_rag_correct_rows": len(flagged) - flagged_errors,
        "unflagged_rag_wrong_rows": unflagged_errors,
        "unflagged_rag_correct_rows": len(unflagged) - unflagged_errors,
        "rag_error_rate_if_flagged": flagged_error_rate,
        "rag_error_rate_if_unflagged": unflagged_error_rate,
        "flagged_vs_unflagged_rag_error_risk_ratio": risk_ratio,
        "poison_selected_rows": len(poison_selected_rows),
        "suspect_poison_rows": len(localized_poison_rows),
        "suspect_clean_only_rows": sum(
            row["conflict_flag"] and not row["suspect_poison_row"] for row in values
        ),
        "poison_localization_precision_given_flag": safe_ratio(
            len(localized_poison_rows), len(flagged)
        ),
        "poison_localization_row_recall": safe_ratio(
            len(localized_poison_rows), len(poison_selected_rows)
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol", type=Path, default=Path("configs/query_aligned_conflict_map_v1.json")
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(
            "artifacts/runs/query_aligned/query_aligned_conflict_map_v1/private_manifest.json"
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
        "--output",
        type=Path,
        default=Path("artifacts/evaluation/query_aligned_conflict_map_v1.json"),
    )
    args = parser.parse_args()

    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    evaluation = json.loads(args.source_evaluation.read_text(encoding="utf-8"))
    if manifest.get("failures") or manifest.get("completed_outputs") != manifest.get(
        "unique_packets"
    ):
        raise ValueError("Conflict-map run is incomplete")
    if len(manifest["rows"]) != protocol["scope"]["expected_rows"]:
        raise ValueError("Conflict-map row coverage differs from the frozen protocol")
    labels = {row_key(row): row for row in evaluation["private_rows"]}
    if len(labels) != len(evaluation["private_rows"]):
        raise ValueError("Source evaluation rows are not unique")

    rows = []
    output_cache = {}
    for descriptor in manifest["rows"]:
        key = row_key(descriptor)
        label = labels.get(key)
        if label is None:
            raise ValueError(f"Missing source evaluation row: {key}")
        output = output_cache.setdefault(
            descriptor["output_path"],
            json.loads(Path(descriptor["output_path"]).read_text(encoding="utf-8")),
        )
        task_key = descriptor["rag_task_key"]
        trace_path = args.trace_root / task_key[:2] / f"{task_key}.json"
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        conflict_indices = eligible_conflict_indices(output["judgment"], trace)
        suspect_ids = suspect_document_ids(output["judgment"], trace)
        flat_documents = {
            str(item["document_id"]): item
            for group in trace["retrievals"]
            for item in group
        }
        suspect_poison_ids = sorted(
            document_id
            for document_id in suspect_ids
            if bool(flat_documents[document_id]["is_poison"])
        )
        poison_selected_indices = []
        for index, (answer, group) in enumerate(
            zip(trace["answers"]["answers"], trace["retrievals"])
        ):
            rank = answer["selected_rank"]
            if rank is not None and bool(group[rank - 1]["is_poison"]):
                poison_selected_indices.append(index)
        comparisons = output["judgment"]["comparisons"]
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
                "stable_internal_question_count": sum(
                    item["internal_state"] == "stable" for item in comparisons
                ),
                "eligible_conflict_count": len(conflict_indices),
                "eligible_conflict_indices": conflict_indices,
                "conflict_flag": bool(conflict_indices),
                "suspect_document_ids": sorted(suspect_ids),
                "suspect_poison_document_ids": suspect_poison_ids,
                "suspect_poison_row": bool(suspect_poison_ids),
                "poison_selected_question_indices": poison_selected_indices,
                "poison_selected_row": bool(poison_selected_indices),
            }
        )

    attacked = [row for row in rows if row["condition_id"] != "clean"]
    condition_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    model_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    model_condition_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        condition_groups[row["condition_id"]].append(row)
        model_groups[row["victim_model_id"]].append(row)
        model_condition_groups[f'{row["victim_model_id"]}::{row["condition_id"]}'].append(row)

    attacked_summary = summarize(attacked)
    gate = protocol["intervention_gate"]
    victims_flagged = len(
        {row["victim_model_id"] for row in attacked if row["conflict_flag"]}
    )
    risk_ratio = attacked_summary["flagged_vs_unflagged_rag_error_risk_ratio"]
    gate_checks = {
        "enough_flagged_attacked_rows": attacked_summary["conflict_flagged_rows"]
        >= gate["minimum_flagged_attacked_rows"],
        "enough_rag_error_enrichment": risk_ratio is not None
        and risk_ratio >= gate["minimum_rag_error_risk_ratio_flagged_vs_unflagged"],
        "enough_victim_models": victims_flagged
        >= gate["minimum_victim_models_with_flagged_attacked_rows"],
    }
    result = {
        "evaluation_schema_version": 1,
        "experiment_id": protocol["experiment_id"],
        "status": "complete_development_conflict_diagnostic",
        "aggregate": summarize(rows),
        "attacked_aggregate": attacked_summary,
        "by_condition": {
            key: summarize(value) for key, value in sorted(condition_groups.items())
        },
        "by_model": {key: summarize(value) for key, value in sorted(model_groups.items())},
        "by_model_condition": {
            key: summarize(value) for key, value in sorted(model_condition_groups.items())
        },
        "intervention_gate": {
            "checks": gate_checks,
            "passed": all(gate_checks.values()),
            "victim_models_with_flagged_attacked_rows": victims_flagged,
        },
        "private_rows": rows,
        "interpretation_boundary": (
            "Conflict flags use only inference-visible answer records. Poison and gold are joined "
            "after outputs solely for evaluation. A suspect passage is not assumed causal."
        ),
    }
    atomic_json(args.output, result)
    print(json.dumps({key: value for key, value in result.items() if key != "private_rows"}, indent=2))


if __name__ == "__main__":
    main()
