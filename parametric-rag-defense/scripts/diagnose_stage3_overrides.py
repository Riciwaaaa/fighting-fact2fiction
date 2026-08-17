#!/usr/bin/env python3
"""Diagnose when Stage 3 overrides help or harm the strongest memory-only anchor."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json


def candidate_prediction(candidate: dict[str, Any]) -> str | None:
    leaders = candidate["leading_verdicts"]
    return leaders[0] if len(leaders) == 1 else None


def outcome(row: dict[str, Any]) -> str:
    stage_correct = row["stage3_prediction"] == row["gold"]
    anchor_correct = row["anchor_prediction"] == row["gold"]
    if stage_correct and not anchor_correct:
        return "gain"
    if anchor_correct and not stage_correct:
        return "regression"
    if stage_correct:
        return "both_correct"
    return "neither_correct"


def aggregate(rows: list[dict[str, Any]], feature: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        values = row[feature] if isinstance(row[feature], list) else [row[feature]]
        for value in values:
            grouped[str(value)].append(row)
    result = {}
    for value, group in sorted(grouped.items()):
        counts = defaultdict(int)
        for row in group:
            counts[outcome(row)] += 1
        result[value] = {
            "overrides": len(group),
            "gain": counts["gain"],
            "regression": counts["regression"],
            "neither_correct": counts["neither_correct"],
            "net_gain": counts["gain"] - counts["regression"],
            "override_precision": counts["gain"] / len(group) if group else None,
        }
    return result


def threshold_sweep(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for threshold in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        predictions = [
            row["stage3_prediction"]
            if row["stage3_confidence"] >= threshold
            else row["anchor_prediction"]
            for row in rows
        ]
        correct = sum(prediction == row["gold"] for prediction, row in zip(predictions, rows))
        accepted = sum(
            row["stage3_prediction"] != row["anchor_prediction"]
            and row["stage3_confidence"] >= threshold
            for row in rows
        )
        result[str(threshold)] = {
            "accuracy": correct / len(rows),
            "correct": correct,
            "accepted_overrides": accepted,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("artifacts/runs/stage3/stage3_claim_arbiter_v1"),
    )
    parser.add_argument(
        "--labels", type=Path, default=Path("artifacts/evaluation/stage1_labels.json")
    )
    parser.add_argument("--anchor-model", default="glm52")
    parser.add_argument("--condition", default="fact2fiction_p0.01")
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/evaluation/stage3_override_diagnostics.json")
    )
    args = parser.parse_args()

    manifest = json.loads((args.run_root / "private_manifest.json").read_text(encoding="utf-8"))
    if manifest["failures"]:
        raise ValueError("Stage 3 manifest contains failures")
    labels = json.loads(args.labels.read_text(encoding="utf-8"))["development"]
    by_arbiter: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for manifest_row in manifest["outputs"]:
        if manifest_row["condition_id"] != args.condition:
            continue
        packet = json.loads(Path(manifest_row["packet_path"]).read_text(encoding="utf-8"))
        output = json.loads(Path(manifest_row["output_path"]).read_text(encoding="utf-8"))
        alias_by_model = {
            model_id: alias
            for alias, model_id in packet["provenance"]["internal_candidate_map"].items()
        }
        candidates = {
            candidate["candidate_id"]: candidate
            for candidate in packet["visible"]["memory_only_assessments"]
        }
        anchor = candidates[alias_by_model[args.anchor_model]]
        judgment = output["arbiter"]["judgment"]
        critic = output["critic"]["judgment"]
        confidence = float(judgment["confidence"])
        if confidence < 0.6:
            confidence_bucket = "low_[0,0.6)"
        elif confidence < 0.8:
            confidence_bucket = "medium_[0.6,0.8)"
        elif confidence < 0.9:
            confidence_bucket = "high_[0.8,0.9)"
        else:
            confidence_bucket = "very_high_[0.9,1]"
        by_arbiter[manifest_row["arbiter_model_id"]].append(
            {
                "claim_id": manifest_row["claim_id"],
                "victim_model_id": manifest_row["victim_model_id"],
                "gold": labels[str(manifest_row["claim_id"])],
                "anchor_prediction": candidate_prediction(anchor),
                "anchor_confidence": anchor["mean_confidence"],
                "anchor_agreement_fraction": anchor["agreement_fraction"],
                "rag_prediction": packet["visible"]["retrieval_assessment"]["verdict"],
                "stage3_prediction": judgment["final_verdict"],
                "stage3_confidence": confidence,
                "confidence_bucket": confidence_bucket,
                "route": judgment["route"],
                "reason_codes": judgment["reason_codes"],
                "critic_direction": critic["evidence_direction"],
                "critic_coverage": critic["coverage"],
                "critic_coherence": critic["coherence"],
                "critic_premise_risk": critic["claim_premise_risk"],
            }
        )

    output: dict[str, Any] = {
        "diagnostic_schema_version": 1,
        "condition": args.condition,
        "anchor_model": args.anchor_model,
        "warning": "METHOD-DESIGN DIAGNOSTIC ONLY; do not select features on validation/test",
        "arbiters": {},
    }
    features = (
        "route",
        "confidence_bucket",
        "victim_model_id",
        "critic_direction",
        "critic_coverage",
        "critic_coherence",
        "critic_premise_risk",
        "reason_codes",
    )
    for arbiter, rows in sorted(by_arbiter.items()):
        overrides = [row for row in rows if row["stage3_prediction"] != row["anchor_prediction"]]
        counts = defaultdict(int)
        for row in overrides:
            counts[outcome(row)] += 1
        anchor_correct = sum(row["anchor_prediction"] == row["gold"] for row in rows)
        stage3_correct = sum(row["stage3_prediction"] == row["gold"] for row in rows)
        output["arbiters"][arbiter] = {
            "pairs": len(rows),
            "anchor_accuracy": anchor_correct / len(rows),
            "stage3_accuracy": stage3_correct / len(rows),
            "overrides": len(overrides),
            "override_outcomes": {
                "gain": counts["gain"],
                "regression": counts["regression"],
                "neither_correct": counts["neither_correct"],
                "net_gain": counts["gain"] - counts["regression"],
                "precision": counts["gain"] / len(overrides) if overrides else None,
            },
            "override_groups": {
                feature: aggregate(overrides, feature) for feature in features
            },
            "confidence_threshold_diagnostic": threshold_sweep(rows),
        }
    atomic_json(args.output, output)
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
