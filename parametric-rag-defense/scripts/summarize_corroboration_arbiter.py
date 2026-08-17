#!/usr/bin/env python3
"""Evaluate frozen same-model corroboration arbitration on development labels."""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json

CONDITIONS = (
    "clean",
    "fact2fiction_p0.001",
    "fact2fiction_p0.0025",
    "fact2fiction_p0.005",
)
SYSTEMS = (
    "rag",
    "memory",
    "answerability_cascade",
    "counter_rule",
    "arbiter_raw",
    "arbiter_guarded",
    "oracle",
)


def identity(row: dict[str, Any]) -> tuple[str, int, str]:
    return (
        str(row["victim_model_id"]),
        int(row["claim_id"]),
        str(row["condition_id"]),
    )


def exact_paired_pvalue(left_only: int, right_only: int) -> float:
    discordant = left_only + right_only
    if not discordant:
        return 1.0
    tail = sum(
        math.comb(discordant, value)
        for value in range(min(left_only, right_only) + 1)
    )
    return min(1.0, 2.0 * tail / (2**discordant))


def claim_bootstrap_delta(
    rows: list[dict[str, Any]], left: str, right: str
) -> list[float]:
    by_claim: dict[int, list[int]] = {}
    for row in rows:
        by_claim.setdefault(int(row["claim_id"]), []).append(
            int(row[f"{left}_correct"]) - int(row[f"{right}_correct"])
        )
    if not by_claim:
        return [0.0, 0.0]
    claims = sorted(by_claim)
    rng = random.Random(20260811)
    samples = []
    for _ in range(5000):
        chosen = rng.choices(claims, k=len(claims))
        deltas = [value for claim in chosen for value in by_claim[claim]]
        samples.append(sum(deltas) / len(deltas))
    samples.sort()
    return [
        samples[int(0.025 * len(samples))],
        samples[int(0.975 * len(samples)) - 1],
    ]


def compare(rows: list[dict[str, Any]], left: str, right: str) -> dict[str, Any]:
    left_only = sum(
        row[f"{left}_correct"] and not row[f"{right}_correct"] for row in rows
    )
    right_only = sum(
        row[f"{right}_correct"] and not row[f"{left}_correct"] for row in rows
    )
    return {
        "left_only_correct": left_only,
        "right_only_correct": right_only,
        "net": left_only - right_only,
        "exact_p": exact_paired_pvalue(left_only, right_only),
        "claim_cluster_bootstrap95_accuracy_delta": claim_bootstrap_delta(
            rows, left, right
        ),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {
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
        "comparisons": {
            f"{method}_vs_{baseline}": compare(rows, method, baseline)
            for method in ("arbiter_raw", "arbiter_guarded")
            for baseline in ("rag", "memory", "answerability_cascade", "counter_rule")
        },
    }
    arbiter_rows = [row for row in rows if row.get("arbiter_action")]
    result["arbiter_rows"] = len(arbiter_rows)
    result["arbiter_actions"] = dict(
        sorted(Counter(row["arbiter_action"] for row in arbiter_rows).items())
    )
    result["guard_acceptance"] = dict(
        sorted(Counter(row["guard_status"] for row in arbiter_rows).items())
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("artifacts/runs/corroboration_arbiter/corroboration_arbiter_v1"),
    )
    parser.add_argument(
        "--answerability",
        type=Path,
        default=Path("artifacts/evaluation/answerability_cascade_v1.json"),
    )
    parser.add_argument(
        "--counter-evaluation",
        type=Path,
        default=Path("artifacts/evaluation/counter_retrieval_signal_v2.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluation/corroboration_arbiter_v1.json"),
    )
    args = parser.parse_args()
    audit = json.loads((args.run_root / "audit.json").read_text(encoding="utf-8"))
    if audit.get("status") != "passed" or audit.get("phase") != "outputs":
        raise ValueError("Corroboration arbiter outputs must pass audit before evaluation")
    manifest = json.loads((args.run_root / "private_manifest.json").read_text(encoding="utf-8"))
    answerability = json.loads(args.answerability.read_text(encoding="utf-8"))
    counter_evaluation = json.loads(
        args.counter_evaluation.read_text(encoding="utf-8")
    )
    base_by_id = {
        identity(row): row
        for row in answerability["private_rows"]
        if row["condition_id"] in CONDITIONS
    }
    counter_by_id = {
        identity(row): row for row in counter_evaluation["private_rows"]
    }

    arbiter_by_id = {}
    for descriptor in manifest["rows"]:
        row_id = identity(descriptor)
        judgment = json.loads(
            Path(descriptor["output_path"]).read_text(encoding="utf-8")
        )["judgment"]
        arbiter_by_id[row_id] = judgment

    rows = []
    for row_id, base in base_by_id.items():
        row = dict(base)
        cascade_endpoint = base["cascade_action"]
        endpoints = {
            "rag": base["rag_prediction"],
            "memory": base["memory_prediction"],
        }
        if row_id in arbiter_by_id:
            judgment = arbiter_by_id[row_id]
            counter = counter_by_id[row_id]
            counter_label = counter["counter_loose_label"]
            if (
                counter_label == base["rag_prediction"]
                and counter_label != base["memory_prediction"]
            ):
                counter_endpoint = "rag"
            elif (
                counter_label == base["memory_prediction"]
                and counter_label != base["rag_prediction"]
            ):
                counter_endpoint = "memory"
            else:
                counter_endpoint = cascade_endpoint
            raw_endpoint = {
                "trust_rag": "rag",
                "trust_memory": "memory",
                "escalate": cascade_endpoint,
            }[judgment["action"]]
            expected_assessment = {
                "rag": "supports_rag",
                "memory": "supports_memory",
            }
            requested_endpoint = (
                "rag"
                if judgment["action"] == "trust_rag"
                else "memory" if judgment["action"] == "trust_memory" else None
            )
            guard_accepts = (
                requested_endpoint is not None
                and requested_endpoint != cascade_endpoint
                and requested_endpoint == counter_endpoint
                and judgment["independent_evidence_assessment"]
                == expected_assessment[requested_endpoint]
            )
            guarded_endpoint = requested_endpoint if guard_accepts else cascade_endpoint
            guard_status = (
                "accepted_override"
                if guard_accepts
                else "same_as_fallback"
                if requested_endpoint == cascade_endpoint
                else "fallback"
            )
            row.update(
                {
                    "arbiter_action": judgment["action"],
                    "arbiter_confidence": judgment["confidence"],
                    "independent_evidence_assessment": judgment[
                        "independent_evidence_assessment"
                    ],
                    "internal_knowledge_assessment": judgment[
                        "internal_knowledge_assessment"
                    ],
                    "cross_view_assessment": judgment["cross_view_assessment"],
                    "guard_status": guard_status,
                }
            )
        else:
            counter_endpoint = cascade_endpoint
            raw_endpoint = cascade_endpoint
            guarded_endpoint = cascade_endpoint
            row.update({"arbiter_action": None, "guard_status": None})

        selected = {
            "rag": "rag",
            "memory": "memory",
            "answerability_cascade": cascade_endpoint,
            "counter_rule": counter_endpoint,
            "arbiter_raw": raw_endpoint,
            "arbiter_guarded": guarded_endpoint,
        }
        for system, endpoint in selected.items():
            row[f"{system}_endpoint"] = endpoint
            row[f"{system}_prediction"] = endpoints[endpoint]
            row[f"{system}_correct"] = endpoints[endpoint] == row["gold"]
        row["oracle_correct"] = base["rag_correct"] or base["memory_correct"]
        rows.append(row)

    models = sorted({row["victim_model_id"] for row in rows})
    output = {
        "evaluation_schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "status": "post_label_development_evaluation",
        "policy": {
            "arbiter_raw": (
                "Copy the requested endpoint; resolve escalate with the answerability cascade."
            ),
            "arbiter_guarded": (
                "Accept an override of the answerability cascade only when the arbiter's "
                "independent-evidence field and the audited counter-map direction both support "
                "the requested endpoint; otherwise use the answerability cascade."
            ),
        },
        "aggregate": {
            condition: summarize(
                [row for row in rows if row["condition_id"] == condition]
            )
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
        "disagreements": summarize(
            [row for row in rows if row["arbiter_action"] is not None]
        ),
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
