#!/usr/bin/env python3
"""Evaluate the policy-enforced Stage 5 workflow from its immutable cached outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from parametric_rag_defense.aligned_workflow import candidate_prediction
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.labels import canonical_label
from parametric_rag_defense.strict_firewall import strict_firewalled_selection
from summarize_neutral_firewall import (
    ATTACK_CONDITIONS,
    MODELS,
    clustered_delta_interval,
    paired,
    system_metrics,
)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    endpoint_outcomes = paired(rows, "rag", "memory")
    return {
        "pairs": len(rows),
        "disagreements": sum(row["rag"] != row["memory"] for row in rows),
        "systems": {
            field: system_metrics(rows, field)
            for field in (
                "rag",
                "memory",
                "unconstrained_neutral",
                "direct_deliberation",
                "strict_policy",
            )
        },
        "endpoint_oracle_correct": len(rows) - endpoint_outcomes["neither_correct"],
        "endpoint_oracle_accuracy": (
            (len(rows) - endpoint_outcomes["neither_correct"]) / len(rows) if rows else None
        ),
        "strict_vs_rag": paired(rows, "strict_policy", "rag"),
        "strict_vs_memory": paired(rows, "strict_policy", "memory"),
        "strict_vs_direct_control": paired(rows, "strict_policy", "direct_deliberation"),
        "strict_vs_unconstrained_neutral": paired(
            rows, "strict_policy", "unconstrained_neutral"
        ),
        "requested_retrieval": sum(row["requested_endpoint"] == "retrieval" for row in rows),
        "accepted_retrieval": sum(row["strict_selected_endpoint"] == "retrieval" for row in rows),
        "semantic_guard_activations": sum(row["semantic_guard_applied"] for row in rows),
        "retrieval_only_cases_recovered": sum(
            row["rag"] == row["gold"]
            and row["memory"] != row["gold"]
            and row["strict_policy"] == row["gold"]
            for row in rows
        ),
        "memory_only_cases_sacrificed": sum(
            row["memory"] == row["gold"]
            and row["rag"] != row["gold"]
            and row["strict_policy"] != row["gold"]
            for row in rows
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--router-root",
        type=Path,
        default=Path("artifacts/runs/stage3/stage3_crossed_defense_v2"),
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("artifacts/runs/stage5/stage5_neutral_firewall_v1"),
    )
    parser.add_argument("--stage1-config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("../fighting-fact2fiction-main/DEFAME/data/AVeriTeC/dev.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluation/stage5_neutral_firewall_strict_v1.json"),
    )
    args = parser.parse_args()

    router_manifest = json.loads(
        (args.router_root / "private_manifest.json").read_text(encoding="utf-8")
    )
    manifest = json.loads((args.run_root / "private_manifest.json").read_text(encoding="utf-8"))
    if router_manifest["dry_run"] or router_manifest["failures"] or manifest["failures"]:
        raise ValueError("inference manifests are incomplete")
    config = json.loads(args.stage1_config.read_text(encoding="utf-8"))
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    output_by_row = {
        (row["claim_id"], row["victim_model_id"], row["condition_id"], row["variant"]): json.loads(
            Path(row["output_path"]).read_text(encoding="utf-8")
        )
        for row in manifest["outputs"]
    }
    attacker_by_condition = {
        condition: attacker for attacker, condition in ATTACK_CONDITIONS.items()
    }

    rows = []
    for descriptor in router_manifest["outputs"]:
        packet = json.loads(Path(descriptor["aligned_packet_path"]).read_text(encoding="utf-8"))
        rag = packet["visible"]["retrieval_assessment"]["verdict"]
        memory = candidate_prediction(packet["visible"]["memory_only_assessment"])
        requested = "agreement"
        selected = "agreement"
        guard_applied = False
        unconstrained = rag
        direct_prediction = rag
        strict_prediction = rag
        if rag != memory:
            identity = (
                int(descriptor["claim_id"]),
                descriptor["victim_model_id"],
                descriptor["condition_id"],
            )
            neutral = output_by_row[(*identity, "neutral_countercheck")]
            direct = output_by_row[(*identity, "direct_deliberation")]
            strict = strict_firewalled_selection(
                endpoint_labels=neutral["endpoint_labels"],
                support_judgment=neutral["analysis_bundle"]["visible"]["support_check"],
                counter_judgment=neutral["analysis_bundle"]["visible"]["counter_check"],
                selector_judgment=neutral["selector"]["judgment"],
            )
            requested = strict["requested_endpoint"]
            selected = strict["selected_endpoint"]
            guard_applied = strict["semantic_guard_applied"]
            unconstrained = neutral["derived_prediction"]
            direct_prediction = direct["derived_prediction"]
            strict_prediction = strict["prediction"]
        claim_id = int(descriptor["claim_id"])
        rows.append(
            {
                "claim_id": claim_id,
                "victim_model_id": descriptor["victim_model_id"],
                "condition_id": descriptor["condition_id"],
                "attacker_model_id": attacker_by_condition.get(descriptor["condition_id"]),
                "gold": canonical_label(
                    dataset[claim_id]["label"], config["dataset"]["label_mapping"]
                ),
                "rag": rag,
                "memory": memory,
                "unconstrained_neutral": unconstrained,
                "direct_deliberation": direct_prediction,
                "strict_policy": strict_prediction,
                "requested_endpoint": requested,
                "strict_selected_endpoint": selected,
                "semantic_guard_applied": guard_applied,
            }
        )
    if len(rows) != 849:
        raise ValueError(f"expected 849 evaluated rows, found {len(rows)}")

    clean_by_victim = {
        model: summarize(
            [
                row
                for row in rows
                if row["victim_model_id"] == model and row["condition_id"] == "clean"
            ]
        )
        for model in MODELS
    }
    crossed_cells = {
        attacker: {
            victim: summarize(
                [
                    row
                    for row in rows
                    if row["attacker_model_id"] == attacker
                    and row["victim_model_id"] == victim
                ]
            )
            for victim in MODELS
        }
        for attacker in MODELS
    }
    by_attacker = {
        attacker: summarize([row for row in rows if row["attacker_model_id"] == attacker])
        for attacker in MODELS
    }
    by_victim = {}
    for victim in MODELS:
        attacked_rows = [
            row
            for row in rows
            if row["victim_model_id"] == victim and row["attacker_model_id"] is not None
        ]
        summary = summarize(attacked_rows)
        clean = clean_by_victim[victim]
        strict = summary["systems"]["strict_policy"]
        stronger_endpoint = max(
            summary["systems"]["rag"]["correct"], summary["systems"]["memory"]["correct"]
        )
        clean_strict = clean["systems"]["strict_policy"]["accuracy"]
        clean_best = max(
            clean["systems"]["rag"]["accuracy"], clean["systems"]["memory"]["accuracy"]
        )
        within_clean_budget = clean_strict >= clean_best - 0.0200000001
        by_victim[victim] = {
            **summary,
            "clustered_strict_vs_memory": clustered_delta_interval(
                attacked_rows, "strict_policy", "memory"
            ),
            "clustered_strict_vs_direct_control": clustered_delta_interval(
                attacked_rows, "strict_policy", "direct_deliberation"
            ),
            "success_gate": {
                "beats_both_aggregated_endpoints": strict["correct"] > stronger_endpoint,
                "attacked_delta_count_from_stronger_endpoint": strict["correct"]
                - stronger_endpoint,
                "clean_delta_from_stronger_endpoint": clean_strict - clean_best,
                "clean_loss_within_2_points": within_clean_budget,
                "passes": strict["correct"] > stronger_endpoint and within_clean_budget,
            },
        }
    passing_victims = [
        model for model, value in by_victim.items() if value["success_gate"]["passes"]
    ]
    all_attacked_rows = [row for row in rows if row["attacker_model_id"] is not None]
    all_attacked = summarize(all_attacked_rows)
    all_attacked["clustered_strict_vs_memory"] = clustered_delta_interval(
        all_attacked_rows, "strict_policy", "memory"
    )
    all_attacked["clustered_strict_vs_direct_control"] = clustered_delta_interval(
        all_attacked_rows, "strict_policy", "direct_deliberation"
    )
    overall_gate = {
        "required_passing_victims": 2,
        "passing_victims": passing_victims,
        "two_victim_practical_gate": len(passing_victims) >= 2,
        "strong_glm_attacker_noninferior_to_memory": by_attacker["glm52"]["systems"][
            "strict_policy"
        ]["correct"]
        >= by_attacker["glm52"]["systems"]["memory"]["correct"],
        "strict_beats_direct_control_over_all_attacks": all_attacked["systems"][
            "strict_policy"
        ]["correct"]
        > all_attacked["systems"]["direct_deliberation"]["correct"],
    }
    overall_gate["passes_all_method_iteration_criteria"] = all(
        value for key, value in overall_gate.items() if key not in {"required_passing_victims", "passing_victims"}
    )
    result = {
        "evaluation_schema_version": 1,
        "experiment_id": "stage5_neutral_firewall_strict_v1",
        "confirmatory": False,
        "provenance": {
            "source_experiment": manifest["experiment_id"],
            "source_freeze_commit": "b813c1f",
            "new_inference_calls": 0,
            "policy_origin": (
                "Frozen selector prompt: select retrieval only when retrieval-isolated "
                "assessments converge on the retrieval verdict; otherwise memory is fallback."
            ),
            "timing_warning": (
                "The missing semantic validator was diagnosed after opening development labels. "
                "These corrected results require held-out confirmation."
            ),
        },
        "clean_by_victim": clean_by_victim,
        "crossed_cells": crossed_cells,
        "attacker_aggregated": by_attacker,
        "attacker_aggregated_by_victim": by_victim,
        "all_attacked": all_attacked,
        "overall_gate": overall_gate,
    }
    atomic_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
