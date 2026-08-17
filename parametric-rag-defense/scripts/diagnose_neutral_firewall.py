#!/usr/bin/env python3
"""Post-label diagnostic for the frozen Stage 5 neutral-firewall experiment."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from parametric_rag_defense.aligned_workflow import candidate_prediction
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.labels import canonical_label
from parametric_rag_defense.strict_firewall import strict_firewalled_selection

ATTACKER_BY_CONDITION = {
    "cross_glm52_p001": "glm52",
    "cross_llama31_70b_p001": "llama31_70b",
    "cross_qwen35_35b_a3b_p001": "qwen35_35b_a3b",
}


def _fraction(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _selection_summary(rows: list[dict[str, Any]], variant: str) -> dict[str, Any]:
    disagreements = [row for row in rows if row["rag"] != row["memory"]]
    retrieval_only = [
        row for row in disagreements if row["rag"] == row["gold"] and row["memory"] != row["gold"]
    ]
    memory_only = [
        row for row in disagreements if row["memory"] == row["gold"] and row["rag"] != row["gold"]
    ]
    neither = [
        row for row in disagreements if row["memory"] != row["gold"] and row["rag"] != row["gold"]
    ]
    retrieval_selected = [row for row in disagreements if row[f"{variant}_selected"] == "retrieval"]
    recovered = sum(row[f"{variant}_prediction"] == row["gold"] for row in retrieval_only)
    sacrificed = sum(row[f"{variant}_prediction"] != row["gold"] for row in memory_only)
    return {
        "rows": len(rows),
        "disagreements": len(disagreements),
        "endpoint_outcomes": {
            "retrieval_only_correct": len(retrieval_only),
            "memory_only_correct": len(memory_only),
            "neither_correct": len(neither),
        },
        "retrieval_selected": len(retrieval_selected),
        "retrieval_selection_rate": _fraction(len(retrieval_selected), len(disagreements)),
        "retrieval_selection_precision": _fraction(
            sum(row["rag"] == row["gold"] for row in retrieval_selected),
            len(retrieval_selected),
        ),
        "retrieval_only_recovered": recovered,
        "retrieval_only_recall": _fraction(recovered, len(retrieval_only)),
        "memory_only_sacrificed": sacrificed,
        "memory_only_false_switch_rate": _fraction(sacrificed, len(memory_only)),
        "net_switch_gain": recovered - sacrificed,
    }


def _neutral_signal_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    disagreements = [row for row in rows if row["rag"] != row["memory"]]
    pair_counts: Counter[str] = Counter()
    pair_correct: Counter[str] = Counter()
    pair_retrieval_selected: Counter[str] = Counter()
    consensus_rows = []
    for row in disagreements:
        support = row["neutral_support_verdict"]
        counter = row["neutral_counter_verdict"]
        key = f"{support} | {counter}"
        pair_counts[key] += 1
        pair_correct[key] += row["neutral_countercheck_prediction"] == row["gold"]
        pair_retrieval_selected[key] += row["neutral_countercheck_selected"] == "retrieval"
        if support == counter:
            consensus_rows.append(row)
    consensus_correct = sum(row["neutral_support_verdict"] == row["gold"] for row in consensus_rows)
    consensus_matches_retrieval = sum(
        row["neutral_support_verdict"] == row["rag"] for row in consensus_rows
    )
    consensus_matches_memory = sum(
        row["neutral_support_verdict"] == row["memory"] for row in consensus_rows
    )
    return {
        "consensus_rows": len(consensus_rows),
        "consensus_accuracy": _fraction(consensus_correct, len(consensus_rows)),
        "consensus_matches_retrieval": consensus_matches_retrieval,
        "consensus_matches_memory": consensus_matches_memory,
        "verdict_pair_behavior": {
            key: {
                "rows": pair_counts[key],
                "selector_accuracy": _fraction(pair_correct[key], pair_counts[key]),
                "retrieval_selected": pair_retrieval_selected[key],
                "retrieval_selection_rate": _fraction(
                    pair_retrieval_selected[key], pair_counts[key]
                ),
            }
            for key in sorted(pair_counts)
        },
    }


def _grouped(
    rows: list[dict[str, Any]], key: Callable[[dict[str, Any]], str]
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    return dict(sorted(groups.items()))


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
        default=Path("artifacts/evaluation/stage5_neutral_firewall_diagnostic_v1.json"),
    )
    args = parser.parse_args()

    router_manifest = json.loads(
        (args.router_root / "private_manifest.json").read_text(encoding="utf-8")
    )
    manifest = json.loads((args.run_root / "private_manifest.json").read_text(encoding="utf-8"))
    config = json.loads(args.stage1_config.read_text(encoding="utf-8"))
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    workflow_outputs = {
        (row["claim_id"], row["victim_model_id"], row["condition_id"], row["variant"]): json.loads(
            Path(row["output_path"]).read_text(encoding="utf-8")
        )
        for row in manifest["outputs"]
    }

    rows = []
    for descriptor in router_manifest["outputs"]:
        packet = json.loads(Path(descriptor["aligned_packet_path"]).read_text(encoding="utf-8"))
        rag = packet["visible"]["retrieval_assessment"]["verdict"]
        memory = candidate_prediction(packet["visible"]["memory_only_assessment"])
        if rag == memory:
            continue
        identity = (
            int(descriptor["claim_id"]),
            descriptor["victim_model_id"],
            descriptor["condition_id"],
        )
        neutral = workflow_outputs[(*identity, "neutral_countercheck")]
        direct = workflow_outputs[(*identity, "direct_deliberation")]
        strict = strict_firewalled_selection(
            endpoint_labels=neutral["endpoint_labels"],
            support_judgment=neutral["analysis_bundle"]["visible"]["support_check"],
            counter_judgment=neutral["analysis_bundle"]["visible"]["counter_check"],
            selector_judgment=neutral["selector"]["judgment"],
        )
        claim_id = identity[0]
        rows.append(
            {
                "claim_id": claim_id,
                "victim_model_id": identity[1],
                "condition_id": identity[2],
                "attacker_model_id": ATTACKER_BY_CONDITION.get(identity[2]),
                "gold": canonical_label(
                    dataset[claim_id]["label"], config["dataset"]["label_mapping"]
                ),
                "rag": rag,
                "memory": memory,
                "neutral_countercheck_prediction": neutral["derived_prediction"],
                "neutral_countercheck_selected": neutral["selector"]["judgment"][
                    "selected_endpoint"
                ],
                "neutral_support_verdict": neutral["analysis_bundle"]["visible"][
                    "support_check"
                ]["verdict"],
                "neutral_counter_verdict": neutral["analysis_bundle"]["visible"][
                    "counter_check"
                ]["verdict"],
                "strict_policy_selected": strict["selected_endpoint"],
                "strict_policy_prediction": strict["prediction"],
                "direct_deliberation_prediction": direct["derived_prediction"],
                "direct_deliberation_selected": direct["selector"]["judgment"][
                    "selected_endpoint"
                ],
            }
        )

    attacked = [row for row in rows if row["attacker_model_id"] is not None]
    result = {
        "diagnostic_schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "warning": "POST-LABEL DIAGNOSTIC; not a frozen selection policy or confirmatory result.",
        "all_attacked": {
            "neutral_countercheck": _selection_summary(attacked, "neutral_countercheck"),
            "strict_policy": _selection_summary(attacked, "strict_policy"),
            "direct_deliberation": _selection_summary(attacked, "direct_deliberation"),
            "neutral_signals": _neutral_signal_summary(attacked),
        },
        "by_victim": {
            model: {
                "neutral_countercheck": _selection_summary(group, "neutral_countercheck"),
                "strict_policy": _selection_summary(group, "strict_policy"),
                "direct_deliberation": _selection_summary(group, "direct_deliberation"),
                "neutral_signals": _neutral_signal_summary(group),
            }
            for model, group in _grouped(attacked, lambda row: row["victim_model_id"]).items()
        },
        "by_attacker": {
            model: {
                "neutral_countercheck": _selection_summary(group, "neutral_countercheck"),
                "strict_policy": _selection_summary(group, "strict_policy"),
                "direct_deliberation": _selection_summary(group, "direct_deliberation"),
                "neutral_signals": _neutral_signal_summary(group),
            }
            for model, group in _grouped(attacked, lambda row: row["attacker_model_id"]).items()
        },
        "clean_by_victim": {
            model: {
                "neutral_countercheck": _selection_summary(group, "neutral_countercheck"),
                "strict_policy": _selection_summary(group, "strict_policy"),
                "direct_deliberation": _selection_summary(group, "direct_deliberation"),
                "neutral_signals": _neutral_signal_summary(group),
            }
            for model, group in _grouped(
                [row for row in rows if row["attacker_model_id"] is None],
                lambda row: row["victim_model_id"],
            ).items()
        },
    }
    atomic_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
