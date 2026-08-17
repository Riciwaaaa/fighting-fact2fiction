#!/usr/bin/env python3
"""Evaluate leave-original-out retrieval as an endpoint arbitration signal."""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json
from summarize_evidence_signal import evidence_label, grouped_probe


CONDITIONS = (
    "clean",
    "fact2fiction_p0.001",
    "fact2fiction_p0.0025",
    "fact2fiction_p0.005",
)
POLICIES = (
    "rag",
    "memory",
    "answerability_cascade",
    "original_loose_then_answerability",
    "original_strict_then_answerability",
    "counter_loose_then_answerability",
    "counter_strict_then_answerability",
    "agreed_loose_then_answerability",
    "agreed_strict_then_answerability",
)


def exact_paired_pvalue(left_only: int, right_only: int) -> float:
    discordant = left_only + right_only
    if discordant == 0:
        return 1.0
    tail = sum(
        math.comb(discordant, value)
        for value in range(min(left_only, right_only) + 1)
    )
    return min(1.0, 2.0 * tail / (2**discordant))


def endpoint_for_label(row: dict[str, Any], label: str | None) -> str | None:
    if label == row["rag_prediction"] and label != row["memory_prediction"]:
        return "rag"
    if label == row["memory_prediction"] and label != row["rag_prediction"]:
        return "memory"
    return None


def choose(row: dict[str, Any], policy: str) -> str:
    if policy in {"rag", "memory"}:
        return policy
    default = row["cascade_action"]
    if policy == "answerability_cascade":
        return default

    strict = "strict" in policy
    original_label = evidence_label(row["original_judgment"], strict=strict)
    counter_label = evidence_label(row["counter_judgment"], strict=strict)
    if policy.startswith("original_"):
        return endpoint_for_label(row, original_label) or default
    if policy.startswith("counter_"):
        return endpoint_for_label(row, counter_label) or default
    if policy.startswith("agreed_"):
        if original_label is not None and original_label == counter_label:
            return endpoint_for_label(row, counter_label) or default
        return default
    raise ValueError(f"Unknown policy: {policy}")


def prediction(row: dict[str, Any], endpoint: str) -> str:
    return row[f"{endpoint}_prediction"]


def claim_bootstrap_delta(
    rows: list[dict[str, Any]], choices: list[str], baseline_choices: list[str]
) -> list[float]:
    """Bootstrap paired accuracy differences by claim, not repeated condition row."""
    values: dict[int, list[int]] = {}
    for row, choice, baseline in zip(rows, choices, baseline_choices):
        delta = int(prediction(row, choice) == row["gold"]) - int(
            prediction(row, baseline) == row["gold"]
        )
        values.setdefault(int(row["claim_id"]), []).append(delta)
    if not values:
        return [0.0, 0.0]
    rng = random.Random(20260811)
    claims = sorted(values)
    samples = []
    for _ in range(5000):
        selected = rng.choices(claims, k=len(claims))
        deltas = [delta for claim in selected for delta in values[claim]]
        samples.append(sum(deltas) / len(deltas))
    samples.sort()
    return [
        samples[int(0.025 * len(samples))],
        samples[int(0.975 * len(samples)) - 1],
    ]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "rows": len(rows),
        "endpoint_disagreements": sum(
            row["rag_prediction"] != row["memory_prediction"] for row in rows
        ),
    }
    choices_by_policy: dict[str, list[str]] = {
        policy: [choose(row, policy) for row in rows] for policy in POLICIES
    }
    correct_by_policy = {
        policy: sum(
            prediction(row, endpoint) == row["gold"]
            for row, endpoint in zip(rows, endpoints)
        )
        for policy, endpoints in choices_by_policy.items()
    }
    result["systems"] = {
        policy: {
            "correct": correct_by_policy[policy],
            "accuracy": correct_by_policy[policy] / len(rows) if rows else None,
            "rag_choices": sum(value == "rag" for value in choices_by_policy[policy]),
            "memory_choices": sum(
                value == "memory" for value in choices_by_policy[policy]
            ),
        }
        for policy in POLICIES
    }
    baseline_choices = choices_by_policy["answerability_cascade"]
    baseline_correct = correct_by_policy["answerability_cascade"]
    for policy in POLICIES[3:]:
        choices = choices_by_policy[policy]
        switched = [
            index
            for index, (choice, baseline) in enumerate(zip(choices, baseline_choices))
            if choice != baseline
        ]
        gains = sum(
            prediction(rows[index], choices[index]) == rows[index]["gold"]
            and prediction(rows[index], baseline_choices[index]) != rows[index]["gold"]
            for index in switched
        )
        regressions = sum(
            prediction(rows[index], choices[index]) != rows[index]["gold"]
            and prediction(rows[index], baseline_choices[index]) == rows[index]["gold"]
            for index in switched
        )
        result["systems"][policy]["vs_answerability"] = {
            "switches": len(switched),
            "unique_switched_claims": len({rows[index]["claim_id"] for index in switched}),
            "unique_switched_model_claims": len(
                {
                    (rows[index]["victim_model_id"], rows[index]["claim_id"])
                    for index in switched
                }
            ),
            "gains": gains,
            "regressions": regressions,
            "net": correct_by_policy[policy] - baseline_correct,
            "exact_p": exact_paired_pvalue(gains, regressions),
            "claim_cluster_bootstrap95_accuracy_delta": claim_bootstrap_delta(
                rows, choices, baseline_choices
            ),
        }
    result["counter_directions"] = dict(
        sorted(
            Counter(
                row["counter_judgment"]["overall_assessment"]["direction"]
                for row in rows
            ).items()
        )
    )
    result["counter_loose_coverage"] = (
        sum(evidence_label(row["counter_judgment"]) is not None for row in rows)
        / len(rows)
        if rows
        else None
    )
    result["counter_strict_coverage"] = (
        sum(
            evidence_label(row["counter_judgment"], strict=True) is not None
            for row in rows
        )
        / len(rows)
        if rows
        else None
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--counter-root",
        type=Path,
        default=Path("artifacts/runs/counter_retrieval/counter_retrieval_signal_v2"),
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("artifacts/runs/evidence_signal/evidence_signal_v1"),
    )
    parser.add_argument(
        "--answerability",
        type=Path,
        default=Path("artifacts/evaluation/answerability_cascade_v1.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluation/counter_retrieval_signal_v2.json"),
    )
    args = parser.parse_args()

    audit = json.loads((args.counter_root / "audit.json").read_text(encoding="utf-8"))
    if audit.get("status") != "passed" or audit.get("phase") != "mapped":
        raise ValueError("Counter-retrieval artifacts must pass the mapped audit")
    counter_manifest = json.loads(
        (args.counter_root / "private_manifest.json").read_text(encoding="utf-8")
    )
    source_manifest = json.loads(
        (args.source_root / "private_manifest.json").read_text(encoding="utf-8")
    )
    answerability = json.loads(args.answerability.read_text(encoding="utf-8"))

    def identity(row: dict[str, Any]) -> tuple[str, int, str]:
        return (
            str(row["victim_model_id"]),
            int(row["claim_id"]),
            str(row["condition_id"]),
        )

    source_by_id = {identity(row): row for row in source_manifest["rows"]}
    answerability_by_id = {
        identity(row): row
        for row in answerability["private_rows"]
        if row["condition_id"] in CONDITIONS
    }
    diagnostic_rows: list[dict[str, Any]] = []
    for descriptor in counter_manifest["rows"]:
        row_id = identity(descriptor)
        source = source_by_id[row_id]
        base = answerability_by_id[row_id]
        original_output = json.loads(
            Path(source["output_path"]).read_text(encoding="utf-8")
        )
        counter_output = json.loads(
            Path(descriptor["output_path"]).read_text(encoding="utf-8")
        )
        original_packet = json.loads(
            Path(source["packet_path"]).read_text(encoding="utf-8")
        )
        counter_packet = json.loads(
            Path(descriptor["counter_packet_path"]).read_text(encoding="utf-8")
        )
        diagnostic_rows.append(
            {
                **base,
                "original_judgment": original_output["judgment"],
                "counter_judgment": counter_output["judgment"],
                "original_packet": original_packet,
                "counter_packet": counter_packet,
            }
        )

    # Project each diagnostic rule to the full evaluated cells. Endpoint agreements are
    # unchanged; only the 363 explicitly mapped disagreements can change action.
    diagnostic_by_id = {identity(row): row for row in diagnostic_rows}
    full_rows: list[dict[str, Any]] = []
    for base in answerability_by_id.values():
        diagnostic = diagnostic_by_id.get(identity(base))
        if diagnostic is None:
            full_rows.append(base)
        else:
            full_rows.append(diagnostic)

    def full_choose(row: dict[str, Any], policy: str) -> str:
        if "counter_judgment" in row:
            return choose(row, policy)
        if policy == "rag":
            return "rag"
        if policy == "memory":
            return "memory"
        # The endpoints agree for every row outside the diagnostic set, so this action
        # is immaterial to the prediction. Keep the actual cascade action for accounting.
        return row["cascade_action"]

    projected = []
    for row in full_rows:
        enriched = dict(row)
        for policy in POLICIES:
            endpoint = full_choose(row, policy)
            enriched[f"{policy}_endpoint"] = endpoint
            enriched[f"{policy}_prediction"] = prediction(row, endpoint)
            enriched[f"{policy}_correct"] = prediction(row, endpoint) == row["gold"]
        projected.append(enriched)

    def summarize_projected(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "rows": len(rows),
            "systems": {
                policy: {
                    "correct": sum(row[f"{policy}_correct"] for row in rows),
                    "accuracy": (
                        sum(row[f"{policy}_correct"] for row in rows) / len(rows)
                        if rows
                        else None
                    ),
                }
                for policy in POLICIES
            },
        }

    models = sorted({row["victim_model_id"] for row in projected})
    output = {
        "evaluation_schema_version": 1,
        "experiment_id": counter_manifest["experiment_id"],
        "status": "post_label_development_diagnostic",
        "interpretation": (
            "All artifacts and fixed counter-retrieval construction were frozen and audited "
            "before labels were joined. Aggregation policies are exploratory development "
            "diagnostics and require a fresh frozen confirmation set."
        ),
        "policy_definitions": {
            "answerability_cascade": (
                "Use same-model closed-book majority when binary; otherwise use RAG."
            ),
            "original_*_then_answerability": (
                "If the original passage report points to exactly one endpoint, use it; "
                "otherwise use the answerability cascade."
            ),
            "counter_*_then_answerability": (
                "If leave-original-out evidence points to exactly one endpoint, use it; "
                "otherwise use the answerability cascade."
            ),
            "agreed_*_then_answerability": (
                "Override the cascade only when original and counter evidence agree on an "
                "endpoint."
            ),
        },
        "disagreements": {
            "aggregate": summarize(diagnostic_rows),
            "by_condition": {
                condition: summarize(
                    [row for row in diagnostic_rows if row["condition_id"] == condition]
                )
                for condition in CONDITIONS
            },
            "by_model_condition": {
                model: {
                    condition: summarize(
                        [
                            row
                            for row in diagnostic_rows
                            if row["victim_model_id"] == model
                            and row["condition_id"] == condition
                        ]
                    )
                    for condition in CONDITIONS
                }
                for model in models
            },
        },
        "projected_full_system": {
            "aggregate": {
                condition: summarize_projected(
                    [row for row in projected if row["condition_id"] == condition]
                )
                for condition in CONDITIONS
            },
            "by_model_condition": {
                model: {
                    condition: summarize_projected(
                        [
                            row
                            for row in projected
                            if row["victim_model_id"] == model
                            and row["condition_id"] == condition
                        ]
                    )
                    for condition in CONDITIONS
                }
                for model in models
            },
        },
        "grouped_probes": {
            "counter_structure_only": grouped_probe(
                [
                    {
                        **row,
                        "packet": row["counter_packet"],
                        "judgment": row["counter_judgment"],
                    }
                    for row in diagnostic_rows
                ],
                include_endpoint_alignment=False,
            ),
            "counter_plus_endpoint_alignment": grouped_probe(
                [
                    {
                        **row,
                        "retrieval_prediction": row["rag_prediction"],
                        "packet": row["counter_packet"],
                        "judgment": row["counter_judgment"],
                    }
                    for row in diagnostic_rows
                ],
                include_endpoint_alignment=True,
            ),
        },
        "private_rows": [
            {
                key: value
                for key, value in row.items()
                if key
                not in {
                    "original_judgment",
                    "counter_judgment",
                    "original_packet",
                    "counter_packet",
                }
            }
            | {
                "original_loose_label": evidence_label(row["original_judgment"]),
                "original_strict_label": evidence_label(
                    row["original_judgment"], strict=True
                ),
                "counter_loose_label": evidence_label(row["counter_judgment"]),
                "counter_strict_label": evidence_label(
                    row["counter_judgment"], strict=True
                ),
            }
            for row in diagnostic_rows
        ],
    }
    atomic_json(args.output, output)
    print(
        json.dumps(
            {
                "status": output["status"],
                "disagreements": output["disagreements"],
                "projected_full_system": output["projected_full_system"],
                "grouped_probes": output["grouped_probes"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
