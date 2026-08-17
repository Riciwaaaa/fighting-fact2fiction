#!/usr/bin/env python3
"""Evaluate fixed-context interventions and guarded development policies."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.query_aligned_internal import localized_conflict_gate


CONDITIONS = (
    "clean",
    "fact2fiction_p0.001",
    "fact2fiction_p0.0025",
    "fact2fiction_p0.005",
)


def row_key(row: dict[str, Any]) -> tuple[str, int, str]:
    return row["victim_model_id"], int(row["claim_id"]), row["condition_id"]


def counter_prediction(row: dict[str, Any]) -> str:
    direction = row["counter_loose_label"]
    endpoints = (row["rag_prediction"], row["memory_prediction"])
    if direction in {"Supported", "Refuted"} and sum(
        direction == endpoint for endpoint in endpoints
    ) == 1:
        return direction
    return row["cascade_prediction"]


def paired_counts(rows: Iterable[dict[str, Any]], policy: str, baseline: str) -> dict[str, int]:
    values = list(rows)
    gains = sum(row[f"{policy}_correct"] and not row[f"{baseline}_correct"] for row in values)
    regressions = sum(
        not row[f"{policy}_correct"] and row[f"{baseline}_correct"] for row in values
    )
    return {
        "gains": gains,
        "regressions": regressions,
        "net": gains - regressions,
        "changed_predictions": sum(row[policy] != row[baseline] for row in values),
        "distinct_gain_claims": len(
            {
                row["claim_id"]
                for row in values
                if row[f"{policy}_correct"] and not row[f"{baseline}_correct"]
            }
        ),
        "distinct_regression_claims": len(
            {
                row["claim_id"]
                for row in values
                if not row[f"{policy}_correct"] and row[f"{baseline}_correct"]
            }
        ),
    }


def disagreement_summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = list(rows)
    return {
        "rows": len(values),
        "intervention_rows": sum(row["intervention"] is not None for row in values),
        "rerun_changed_from_rag": sum(row["rerun_changed_from_rag"] for row in values),
        "localized_causal_activations": sum(row["localized_causal_activation"] for row in values),
        "raw_replace_correct": sum(row["raw_replace_correct"] for row in values),
        "raw_causal_counter_correct": sum(row["raw_causal_counter_correct"] for row in values),
        "localized_answerability_correct": sum(
            row["localized_answerability_correct"] for row in values
        ),
        "localized_counter_correct": sum(row["localized_counter_correct"] for row in values),
        "counter_correct": sum(row["counter_correct"] for row in values),
        "cascade_correct": sum(row["cascade_correct"] for row in values),
        "localized_vs_counter": paired_counts(values, "localized_counter", "counter"),
        "raw_causal_vs_counter": paired_counts(values, "raw_causal_counter", "counter"),
    }


def project_group(
    rows: list[dict[str, Any]], base_group: dict[str, Any]
) -> dict[str, Any]:
    systems = base_group["systems"]
    base_counter = systems["counter_loose_then_answerability"]["correct"]
    base_cascade = systems["answerability_cascade"]["correct"]
    disagreement_counter = sum(row["counter_correct"] for row in rows)
    disagreement_cascade = sum(row["cascade_correct"] for row in rows)
    localized_counter = base_counter + sum(
        row["localized_counter_correct"] for row in rows
    ) - disagreement_counter
    localized_answerability = base_cascade + sum(
        row["localized_answerability_correct"] for row in rows
    ) - disagreement_cascade
    raw_causal = base_counter + sum(
        row["raw_causal_counter_correct"] for row in rows
    ) - disagreement_counter
    raw_replace = (
        base_counter
        + sum(row["raw_replace_correct"] for row in rows)
        - disagreement_counter
    )
    total = int(base_group["rows"])
    return {
        "rows": total,
        "systems": {
            "rag": systems["rag"],
            "memory": systems["memory"],
            "answerability_cascade": systems["answerability_cascade"],
            "counter_corroboration": systems["counter_loose_then_answerability"],
            "localized_answerability": {
                "correct": localized_answerability,
                "accuracy": localized_answerability / total,
            },
            "localized_counter_extension": {
                "correct": localized_counter,
                "accuracy": localized_counter / total,
            },
            "raw_causal_counter_extension": {
                "correct": raw_causal,
                "accuracy": raw_causal / total,
            },
            "raw_replace_counter_extension": {
                "correct": raw_replace,
                "accuracy": raw_replace / total,
            },
        },
        "localized_extension_vs_counter": paired_counts(
            rows, "localized_counter", "counter"
        ),
    }


def clustered_interval(rows: list[dict[str, Any]], *, samples: int = 10000) -> dict[str, Any]:
    by_claim: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_claim[row["claim_id"]].append(row)
    claims = sorted(by_claim)
    rng = random.Random(710)
    estimates = []
    for _ in range(samples):
        selected = [rng.choice(claims) for _ in claims]
        numerator = 0
        denominator = 0
        for claim_id in selected:
            group = by_claim[claim_id]
            numerator += sum(
                int(row["localized_counter_correct"]) - int(row["counter_correct"])
                for row in group
            )
            denominator += len(group)
        estimates.append(numerator / denominator if denominator else 0.0)
    estimates.sort()
    return {
        "unit": "claim-clustered disagreement-row accuracy difference",
        "samples": samples,
        "seed": 710,
        "point": sum(
            int(row["localized_counter_correct"]) - int(row["counter_correct"])
            for row in rows
        )
        / len(rows),
        "percentile_95": [
            estimates[int(0.025 * samples)],
            estimates[int(0.975 * samples) - 1],
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-evaluation",
        type=Path,
        default=Path("artifacts/evaluation/counter_retrieval_signal_v2.json"),
    )
    parser.add_argument(
        "--conflict-evaluation",
        type=Path,
        default=Path("artifacts/evaluation/query_aligned_conflict_map_v1.json"),
    )
    parser.add_argument(
        "--intervention-manifest",
        type=Path,
        default=Path(
            "artifacts/runs/query_aligned/query_aligned_intervention_v1/private_manifest.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluation/query_aligned_intervention_v1.json"),
    )
    args = parser.parse_args()

    base = json.loads(args.base_evaluation.read_text(encoding="utf-8"))
    conflict = json.loads(args.conflict_evaluation.read_text(encoding="utf-8"))
    intervention = json.loads(args.intervention_manifest.read_text(encoding="utf-8"))
    if intervention.get("failures") or intervention.get("completed_outputs") != intervention.get(
        "intervention_rows"
    ):
        raise ValueError("Intervention run is incomplete")
    conflict_rows = {row_key(row): row for row in conflict["private_rows"]}
    intervention_rows = {}
    for descriptor in intervention["rows"]:
        output = json.loads(Path(descriptor["output_path"]).read_text(encoding="utf-8"))
        intervention_rows[row_key(descriptor)] = {
            "verdict": output["verdict"]["verdict"],
            "confidence": output["verdict"]["confidence"],
            "removed_poison": bool(descriptor["removed_poison_document_ids"]),
        }

    rows = []
    for source in base["private_rows"]:
        key = row_key(source)
        conflict_row = conflict_rows[key]
        intervention_row = intervention_rows.get(key)
        counter = counter_prediction(source)
        rerun = intervention_row["verdict"] if intervention_row else None
        raw_replace = rerun or counter
        raw_causal_activation = rerun is not None and rerun != source["rag_prediction"]
        raw_causal_counter = rerun if raw_causal_activation else counter
        localized = localized_conflict_gate(
            stable_questions=conflict_row["stable_internal_question_count"],
            conflict_questions=conflict_row["eligible_conflict_count"],
        )
        localized_activation = raw_causal_activation and localized
        localized_counter = rerun if localized_activation else counter
        localized_answerability = (
            rerun if localized_activation else source["cascade_prediction"]
        )
        row = {
            **source,
            "counter": counter,
            "counter_correct": counter == source["gold"],
            "intervention": rerun,
            "intervention_confidence": intervention_row["confidence"]
            if intervention_row
            else None,
            "removed_poison": intervention_row["removed_poison"]
            if intervention_row
            else None,
            "stable_internal_question_count": conflict_row[
                "stable_internal_question_count"
            ],
            "eligible_conflict_count": conflict_row["eligible_conflict_count"],
            "localized_conflict": localized,
            "rerun_changed_from_rag": raw_causal_activation,
            "localized_causal_activation": localized_activation,
            "raw_replace": raw_replace,
            "raw_replace_correct": raw_replace == source["gold"],
            "raw_causal_counter": raw_causal_counter,
            "raw_causal_counter_correct": raw_causal_counter == source["gold"],
            "localized_counter": localized_counter,
            "localized_counter_correct": localized_counter == source["gold"],
            "localized_answerability": localized_answerability,
            "localized_answerability_correct": localized_answerability == source["gold"],
        }
        rows.append(row)

    condition_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    model_condition_rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        condition_rows[row["condition_id"]].append(row)
        model_condition_rows[(row["victim_model_id"], row["condition_id"])].append(row)

    projected_aggregate = {
        condition: project_group(
            condition_rows[condition],
            base["projected_full_system"]["aggregate"][condition],
        )
        for condition in CONDITIONS
    }
    projected_by_model_condition = {}
    for model_id, condition_map in base["projected_full_system"][
        "by_model_condition"
    ].items():
        projected_by_model_condition[model_id] = {
            condition: project_group(
                model_condition_rows[(model_id, condition)], condition_map[condition]
            )
            for condition in CONDITIONS
        }

    clean_ok = (
        projected_aggregate["clean"]["systems"]["localized_counter_extension"][
            "correct"
        ]
        >= projected_aggregate["clean"]["systems"]["counter_corroboration"]["correct"]
    )
    attacked_strict_better = all(
        projected_aggregate[condition]["systems"]["localized_counter_extension"][
            "correct"
        ]
        > projected_aggregate[condition]["systems"]["counter_corroboration"]["correct"]
        for condition in CONDITIONS[1:]
    )
    victim_nets = {}
    for model_id in projected_by_model_condition:
        victim_rows = [
            row
            for row in rows
            if row["victim_model_id"] == model_id and row["condition_id"] != "clean"
        ]
        victim_nets[model_id] = paired_counts(
            victim_rows, "localized_counter", "counter"
        )["net"]

    attacked_rows = [row for row in rows if row["condition_id"] != "clean"]
    result = {
        "evaluation_schema_version": 1,
        "experiment_id": "query_aligned_intervention_v1",
        "status": "complete_post_label_development_evaluation",
        "policy_definitions": {
            "raw_replace": "Use every fixed-context rerun verdict on conflict-flagged rows.",
            "raw_causal_counter": (
                "Override corroboration only when fixed-context removal changes RAG."
            ),
            "localized_answerability": (
                "Use answerability by default; override only for a causal change with 2+ "
                "conflicts covering at most one third of stable question answers."
            ),
            "localized_counter": (
                "Use the selected corroboration method by default; apply the same localized "
                "causal override."
            ),
        },
        "disagreements": {
            "aggregate": disagreement_summary(rows),
            "attacked": disagreement_summary(attacked_rows),
            "by_condition": {
                condition: disagreement_summary(condition_rows[condition])
                for condition in CONDITIONS
            },
            "by_model_condition": {
                f"{model_id}::{condition}": disagreement_summary(group)
                for (model_id, condition), group in sorted(model_condition_rows.items())
            },
        },
        "projected_full_system": {
            "aggregate": projected_aggregate,
            "by_model_condition": projected_by_model_condition,
        },
        "localized_extension_uncertainty": clustered_interval(attacked_rows),
        "adoption_gate": {
            "clean_not_below_counter": clean_ok,
            "strictly_better_at_every_attacked_rate": attacked_strict_better,
            "victim_attacked_net_gains": victim_nets,
            "no_victim_net_loss_beyond_one": all(
                value >= -1 for value in victim_nets.values()
            ),
            "descriptive_gate_passed": clean_ok
            and attacked_strict_better
            and all(value >= -1 for value in victim_nets.values()),
            "confirmation_passed": False,
        },
        "private_rows": rows,
        "interpretation": (
            "The localized rule is selected after development error analysis. Its three row-level "
            "gains come from two distinct claims, so it requires fresh confirmation and cannot yet "
            "replace the previously frozen candidate."
        ),
    }
    atomic_json(args.output, result)
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "private_rows"},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
