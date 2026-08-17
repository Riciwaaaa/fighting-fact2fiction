#!/usr/bin/env python3
"""Evaluate the frozen policy on the prespecified two-attacker transfer matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_stage2_packets import internal_lookup
from evaluate_environment_confirmation import endpoint_prediction, summarize
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.environment_drift import drift_alarm, drift_level
from parametric_rag_defense.labels import canonical_label, deterministic_majority
from summarize_evidence_signal import evidence_label


def identity(row: dict[str, Any]) -> tuple[str, str, int]:
    return (
        row["attacker_model_id"],
        row["victim_model_id"],
        int(row["claim_id"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("configs/environment_confirmation_protocol_v1.json"),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/stage1_environment_confirmation_train_v1.json"),
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=Path(
            "artifacts/runs/environment_confirmation_train_v1/stage1/confirmation/rag/"
            "environment_confirmation_attacker_transfer_v1/manifests/transfer_manifest.json"
        ),
    )
    parser.add_argument(
        "--counter-root",
        type=Path,
        default=Path(
            "artifacts/runs/environment_confirmation_train_v1/attacker_transfer_counter/"
            "environment_confirmation_transfer_counter_v1"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "artifacts/evaluation/environment_confirmation_train_v1/"
            "attacker_transfer_results.json"
        ),
    )
    args = parser.parse_args()

    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    source = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    counter_audit = json.loads(
        (args.counter_root / "audit.json").read_text(encoding="utf-8")
    )
    counter = json.loads(
        (args.counter_root / "private_manifest.json").read_text(encoding="utf-8")
    )
    if counter_audit.get("status") != "passed":
        raise ValueError("attacker-transfer audit must pass before evaluation")
    if source.get("failures") or counter.get("failures"):
        raise ValueError("attacker-transfer inputs retain runtime failures")

    dataset = json.loads(Path(config["dataset"]["source"]).read_text(encoding="utf-8"))
    active_split = config["dataset"].get("active_split", "development")
    samples, _ = internal_lookup(
        config,
        Path(config["run_root"]) / active_split / "internal_endpoint",
        Path(config["cache_root"]),
    )
    memory = {
        model_id: {
            int(claim_id): deterministic_majority(value["verdict"] for value in judgments)
            for claim_id, judgments in claim_samples.items()
        }
        for model_id, claim_samples in samples.items()
    }
    counter_labels = {}
    for descriptor in counter["rows"]:
        judgment = json.loads(
            Path(descriptor["output_path"]).read_text(encoding="utf-8")
        )["judgment"]
        counter_labels[identity(descriptor)] = (
            evidence_label(judgment),
            evidence_label(judgment, strict=True),
        )

    rows = []
    for descriptor in source["successes"]:
        endpoint = json.loads(
            Path(descriptor["artifact_path"]).read_text(encoding="utf-8")
        )
        victim = descriptor["victim_model_id"]
        claim_id = int(descriptor["claim_id"])
        rag_prediction = endpoint["judgment"]["verdict"]
        memory_prediction = memory[victim][claim_id]
        memory_answerable = memory_prediction in {"Supported", "Refuted"}
        row = {
            "attacker_model_id": descriptor["attacker_model_id"],
            "victim_model_id": victim,
            "claim_id": claim_id,
            "condition_id": descriptor["condition_id"],
            "rag_task_key": descriptor["task_key"],
            "gold": canonical_label(
                dataset[claim_id]["label"], config["dataset"]["label_mapping"]
            ),
            "rag_prediction": rag_prediction,
            "memory_prediction": memory_prediction,
            "memory_answerable": memory_answerable,
            "answerability_prediction": (
                memory_prediction if memory_answerable else rag_prediction
            ),
        }
        row_id = identity(row)
        if rag_prediction != memory_prediction and row_id not in counter_labels:
            raise ValueError(f"missing counter report for disagreement {row_id}")
        loose_label, strict_label = counter_labels.get(row_id, (None, None))
        row["loose_prediction"] = endpoint_prediction(row, loose_label)
        row["strict_prediction"] = endpoint_prediction(row, strict_label)
        row["oracle_prediction"] = (
            row["gold"]
            if row["gold"] in {rag_prediction, memory_prediction}
            else row["answerability_prediction"]
        )
        rows.append(row)

    reference = protocol["selected_policy"]["fixed_clean_reference"]
    minimum = int(protocol["selected_policy"]["minimum_answerable_observations"])
    attackers = list(protocol["attacker_transfer_secondary"]["attackers"])
    victims = list(protocol["same_model_primary_matrix"]["models"])
    cell_drift = {}
    for attacker in attackers:
        cell_drift[attacker] = {}
        for victim in victims:
            scoped = [
                row
                for row in rows
                if row["attacker_model_id"] == attacker
                and row["victim_model_id"] == victim
            ]
            signal = drift_alarm(
                scoped,
                clean_disagreements=int(reference[victim]["disagreements"]),
                clean_eligible=int(reference[victim]["answerable"]),
                significance=0.01,
                minimum_eligible=minimum,
            )
            signal["drift_level"] = (
                drift_level(signal["posterior_predictive_upper_tail"])
                if signal["eligible"] >= minimum
                else "normal"
            )
            cell_drift[attacker][victim] = signal

    for row in rows:
        row["drift_level"] = cell_drift[row["attacker_model_id"]][
            row["victim_model_id"]
        ]["drift_level"]
        row["proposed_prediction"] = {
            "normal": row["loose_prediction"],
            "warning": row["strict_prediction"],
            "critical": row["answerability_prediction"],
        }[row["drift_level"]]

    by_cell = {
        attacker: {
            victim: summarize(
                [
                    row
                    for row in rows
                    if row["attacker_model_id"] == attacker
                    and row["victim_model_id"] == victim
                ]
            )
            for victim in victims
        }
        for attacker in attackers
    }
    by_attacker = {
        attacker: summarize(
            [row for row in rows if row["attacker_model_id"] == attacker]
        )
        for attacker in attackers
    }
    by_victim = {
        victim: summarize([row for row in rows if row["victim_model_id"] == victim])
        for victim in victims
    }
    result = {
        "evaluation_schema_version": 1,
        "experiment_id": "environment_confirmation_attacker_transfer_v1",
        "status": "prespecified_secondary_evaluated_without_retuning",
        "scope": {
            "claims": len(source["common_claim_ids"]),
            "rows": len(rows),
            "attackers": attackers,
            "victims": victims,
            "nominal_rate": 0.01,
            "attacker_identity_used_for_inference": False,
        },
        "cell_drift": cell_drift,
        "pooled": summarize(rows),
        "by_attacker": by_attacker,
        "by_victim": by_victim,
        "by_attacker_victim": by_cell,
        "private_rows": rows,
    }
    atomic_json(args.output, result)
    print(json.dumps({key: value for key, value in result.items() if key != "private_rows"}, indent=2))


if __name__ == "__main__":
    main()
