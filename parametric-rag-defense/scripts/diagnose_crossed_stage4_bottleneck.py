#!/usr/bin/env python3
"""Diagnose where the crossed Stage C workflow gains and loses endpoint disagreements."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from parametric_rag_defense.aligned_workflow import candidate_prediction
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.labels import canonical_label

ATTACKER_BY_CONDITION = {
    "cross_glm52_p001": "glm52",
    "cross_llama31_70b_p001": "llama31_70b",
    "cross_qwen35_35b_a3b_p001": "qwen35_35b_a3b",
}


def endpoint_correct(endpoint: str, row: dict[str, Any]) -> bool:
    field = "rag" if endpoint == "retrieval" else "memory"
    return row[field] == row["gold"]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    transitions = Counter()
    change_outcomes = Counter()
    check_bases = Counter()
    check_alignments = Counter()
    final_endpoints = Counter()
    followed_alignment = Counter()
    cases: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        router_correct = endpoint_correct(row["router_endpoint"], row)
        final_correct = endpoint_correct(row["final_endpoint"], row)
        transitions[f"router_{'correct' if router_correct else 'wrong'}__final_{'correct' if final_correct else 'wrong'}"] += 1
        changed = row["router_endpoint"] != row["final_endpoint"]
        if changed:
            outcome = "beneficial" if final_correct and not router_correct else "harmful" if router_correct and not final_correct else "neutral"
            change_outcomes[outcome] += 1
            cases[f"selector_change_{outcome}"].append(
                {
                    "claim_id": row["claim_id"],
                    "victim_model_id": row["victim_model_id"],
                    "router_endpoint": row["router_endpoint"],
                    "final_endpoint": row["final_endpoint"],
                    "check_verdict": row["check_verdict"],
                    "check_knowledge_basis": row["check_knowledge_basis"],
                    "check_alignment_heuristic": row["check_alignment_heuristic"],
                }
            )
        check_bases[row["check_knowledge_basis"]] += 1
        check_alignments[row["check_alignment_heuristic"]] += 1
        final_endpoints[row["final_endpoint"]] += 1
        alignment = row["check_alignment_heuristic"]
        if alignment in {"retrieval", "memory"}:
            followed_alignment["followed" if row["final_endpoint"] == alignment else "rejected"] += 1
            followed_alignment[
                f"aligned_endpoint_{'correct' if endpoint_correct(alignment, row) else 'wrong'}"
            ] += 1
        if row["memory"] == row["gold"] and row["rag"] != row["gold"]:
            cases["memory_only"].append(
                {
                    "claim_id": row["claim_id"],
                    "victim_model_id": row["victim_model_id"],
                    "router_endpoint": row["router_endpoint"],
                    "final_endpoint": row["final_endpoint"],
                    "check_verdict": row["check_verdict"],
                    "check_knowledge_basis": row["check_knowledge_basis"],
                    "check_alignment_heuristic": row["check_alignment_heuristic"],
                }
            )
        if row["rag"] == row["gold"] and row["memory"] != row["gold"]:
            cases["retrieval_only"].append(
                {
                    "claim_id": row["claim_id"],
                    "victim_model_id": row["victim_model_id"],
                    "router_endpoint": row["router_endpoint"],
                    "final_endpoint": row["final_endpoint"],
                    "check_verdict": row["check_verdict"],
                    "check_knowledge_basis": row["check_knowledge_basis"],
                    "check_alignment_heuristic": row["check_alignment_heuristic"],
                }
            )
    memory_only = cases["memory_only"]
    retrieval_only = cases["retrieval_only"]
    return {
        "disagreements": len(rows),
        "router_correct": sum(endpoint_correct(row["router_endpoint"], row) for row in rows),
        "final_correct": sum(endpoint_correct(row["final_endpoint"], row) for row in rows),
        "router_to_final_transitions": dict(sorted(transitions.items())),
        "selector_changes": {
            "total": sum(change_outcomes.values()),
            **dict(sorted(change_outcomes.items())),
        },
        "check_knowledge_basis": dict(sorted(check_bases.items())),
        "check_alignment_heuristic": dict(sorted(check_alignments.items())),
        "selector_vs_check_alignment": dict(sorted(followed_alignment.items())),
        "final_endpoints": dict(sorted(final_endpoints.items())),
        "endpoint_only_opportunities": {
            "memory_only": len(memory_only),
            "memory_only_preserved": sum(row["final_endpoint"] == "memory" for row in memory_only),
            "memory_only_sacrificed": sum(row["final_endpoint"] != "memory" for row in memory_only),
            "retrieval_only": len(retrieval_only),
            "retrieval_only_recovered": sum(row["final_endpoint"] == "retrieval" for row in retrieval_only),
            "retrieval_only_missed": sum(row["final_endpoint"] != "retrieval" for row in retrieval_only),
        },
        "cases": dict(sorted(cases.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage4-root",
        type=Path,
        default=Path("artifacts/runs/stage4/stage4_crossed_defense_v2"),
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
        default=Path("artifacts/evaluation/stage4_crossed_bottleneck_diagnostic_v1.json"),
    )
    args = parser.parse_args()

    manifest = json.loads((args.stage4_root / "private_manifest.json").read_text(encoding="utf-8"))
    if manifest["failures"] or len(manifest["outputs"]) != manifest["target_disagreements"]:
        raise ValueError("Stage C manifest is incomplete")
    config = json.loads(args.stage1_config.read_text(encoding="utf-8"))
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for descriptor in manifest["outputs"]:
        condition = descriptor["condition_id"]
        if condition not in ATTACKER_BY_CONDITION:
            continue
        packet = json.loads(Path(descriptor["aligned_packet_path"]).read_text(encoding="utf-8"))
        router_output = json.loads(Path(descriptor["router_output_path"]).read_text(encoding="utf-8"))
        stage4_output = json.loads(Path(descriptor["output_path"]).read_text(encoding="utf-8"))
        rag = packet["visible"]["retrieval_assessment"]["verdict"]
        memory = candidate_prediction(packet["visible"]["memory_only_assessment"])
        if rag == memory:
            raise ValueError("Stage C descriptor unexpectedly contains endpoint agreement")
        check = stage4_output["proposition_check"]["judgment"]
        check_verdict = check["verdict"]
        check_alignment = (
            "retrieval"
            if check_verdict == rag and check_verdict != memory
            else "memory"
            if check_verdict == memory and check_verdict != rag
            else "neither"
        )
        claim_id = int(descriptor["claim_id"])
        rows.append(
            {
                "claim_id": claim_id,
                "attacker_model_id": ATTACKER_BY_CONDITION[condition],
                "victim_model_id": descriptor["victim_model_id"],
                "gold": canonical_label(dataset[claim_id]["label"], config["dataset"]["label_mapping"]),
                "rag": rag,
                "memory": memory,
                "router_endpoint": router_output["router"]["judgment"]["provisional_endpoint"],
                "final_endpoint": stage4_output["final_selector"]["judgment"]["selected_endpoint"],
                "check_verdict": check_verdict,
                "check_knowledge_basis": check["knowledge_basis"],
                "check_alignment_heuristic": check_alignment,
            }
        )

    by_attacker = {
        attacker: summarize([row for row in rows if row["attacker_model_id"] == attacker])
        for attacker in ATTACKER_BY_CONDITION.values()
    }
    by_victim = {
        victim: summarize([row for row in rows if row["victim_model_id"] == victim])
        for victim in sorted({row["victim_model_id"] for row in rows})
    }
    result = {
        "diagnostic_schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "warning": (
            "POST-EVALUATION DEVELOPMENT DIAGNOSTIC. Direct equality between a pivotal-proposition "
            "verdict and an endpoint verdict is only a polarity heuristic, not a gold assessment "
            "of the proposition itself."
        ),
        "attacked_disagreements": len(rows),
        "overall": summarize(rows),
        "by_attacker": by_attacker,
        "by_victim": by_victim,
    }
    atomic_json(args.output, result)
    compact = {
        "attacked_disagreements": result["attacked_disagreements"],
        "overall": {key: value for key, value in result["overall"].items() if key != "cases"},
        "by_attacker": {
            key: {child: value for child, value in summary.items() if child != "cases"}
            for key, summary in by_attacker.items()
        },
        "by_victim": {
            key: {child: value for child, value in summary.items() if child != "cases"}
            for key, summary in by_victim.items()
        },
    }
    print(json.dumps(compact, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
