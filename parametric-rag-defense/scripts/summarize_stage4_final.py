#!/usr/bin/env python3
"""Consolidate frozen Stage C, exact-budget control, and endpoint results."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from parametric_rag_defense.aligned_workflow import candidate_prediction
from parametric_rag_defense.averitec import atomic_json

LABELS = ("Supported", "Refuted")


def manifest(root: Path) -> dict[str, Any]:
    value = json.loads((root / "private_manifest.json").read_text(encoding="utf-8"))
    if value.get("dry_run") or value.get("failures"):
        raise ValueError(f"Invalid input manifest: {root}")
    return value


def metrics(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    correct = sum(row[field] == row["gold"] for row in rows)
    f1 = []
    for label in LABELS:
        tp = sum(row[field] == label and row["gold"] == label for row in rows)
        fp = sum(row[field] == label and row["gold"] != label for row in rows)
        fn = sum(row[field] != label and row["gold"] == label for row in rows)
        denominator = 2 * tp + fp + fn
        f1.append(2 * tp / denominator if denominator else 0.0)
    return {
        "correct": correct,
        "total": len(rows),
        "accuracy": correct / len(rows) if rows else None,
        "macro_f1": sum(f1) / len(f1) if f1 else None,
        "nonbinary": sum(row[field] not in LABELS for row in rows),
    }


def paired(rows: list[dict[str, Any]], first: str, second: str) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for row in rows:
        first_correct = row[first] == row["gold"]
        second_correct = row[second] == row["gold"]
        key = (
            "both_correct"
            if first_correct and second_correct
            else "first_only_correct"
            if first_correct
            else "second_only_correct"
            if second_correct
            else "neither_correct"
        )
        counts[key] += 1
    result: dict[str, Any] = {
        key: counts[key]
        for key in ("both_correct", "first_only_correct", "second_only_correct", "neither_correct")
    }
    discordant = result["first_only_correct"] + result["second_only_correct"]
    if discordant:
        smaller = min(result["first_only_correct"], result["second_only_correct"])
        tail = sum(math.comb(discordant, i) * 0.5**discordant for i in range(smaller + 1))
        result["two_sided_exact_mcnemar_p"] = min(1.0, 2 * tail)
    else:
        result["two_sided_exact_mcnemar_p"] = 1.0
    return result


def output_map(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {row["aligned_packet_key"]: row for row in value["outputs"]}
    if len(result) != len(value["outputs"]):
        raise ValueError("Duplicate aligned packet keys in Stage C manifest")
    return result


def cache_usage(cache_root: Path, keys: list[str]) -> dict[str, Any]:
    unique_keys = sorted(set(keys))
    prompt_tokens = completion_tokens = total_tokens = 0
    latency_ms = 0.0
    for key in unique_keys:
        entry = json.loads(
            (cache_root / "entries" / key[:2] / f"{key}.json").read_text(encoding="utf-8")
        )
        if entry["key"] != key or not entry["response"].get("contract_ok"):
            raise ValueError(f"Invalid referenced cache entry: {key}")
        usage = entry["response"].get("usage") or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
        total_tokens += int(usage.get("total_tokens") or 0)
        latency_ms += float(entry["response"].get("latency_ms") or 0.0)
    return {
        "references": len(keys),
        "unique_provider_responses": len(unique_keys),
        "prompt_tokens_unique": prompt_tokens,
        "completion_tokens_unique": completion_tokens,
        "total_tokens_unique": total_tokens,
        "summed_provider_latency_seconds_unique": latency_ms / 1000,
    }


def assemble(
    *,
    split: str,
    router_manifest: dict[str, Any],
    treatment_manifest: dict[str, Any],
    control_manifest: dict[str, Any],
    labels: dict[str, str],
) -> list[dict[str, Any]]:
    treatment = output_map(treatment_manifest)
    control = output_map(control_manifest)
    rows = []
    for descriptor in router_manifest["outputs"]:
        if descriptor["victim_model_id"] != "llama31_70b" or descriptor["variant"] != "endpoint_only":
            continue
        if descriptor["condition_id"] not in ("clean", "fact2fiction_p0.01"):
            continue
        packet = json.loads(Path(descriptor["aligned_packet_path"]).read_text(encoding="utf-8"))
        router_output = json.loads(Path(descriptor["output_path"]).read_text(encoding="utf-8"))
        rag = packet["visible"]["retrieval_assessment"]["verdict"]
        memory = candidate_prediction(packet["visible"]["memory_only_assessment"])
        if memory is None:
            raise ValueError(f"Ambiguous memory endpoint for claim {descriptor['claim_id']}")
        disagreement = rag != memory
        treatment_prediction = memory
        control_prediction = memory
        treatment_endpoint = "agreement"
        control_endpoint = "agreement"
        proposition = None
        proposition_basis = "not_activated"
        proposition_fallback = False
        if disagreement:
            key = packet["packet_key"]
            if key not in treatment or key not in control:
                raise ValueError(f"Missing treatment/control output for {split} packet {key}")
            treatment_descriptor = treatment[key]
            control_descriptor = control[key]
            treatment_output = json.loads(
                Path(treatment_descriptor["output_path"]).read_text(encoding="utf-8")
            )
            treatment_prediction = treatment_descriptor["prediction"]
            control_prediction = control_descriptor["prediction"]
            treatment_endpoint = treatment_descriptor["selected_endpoint"]
            control_endpoint = control_descriptor["selected_endpoint"]
            proposition_record = treatment_output["proposition_check"]
            proposition = proposition_record["proposition"]
            proposition_basis = proposition_record["judgment"]["knowledge_basis"]
            proposition_fallback = proposition == (
                "Whether the original claim's central factual assertion is accurate as stated."
            )
        rows.append(
            {
                "split": split,
                "claim_id": descriptor["claim_id"],
                "condition_id": descriptor["condition_id"],
                "gold": labels[str(descriptor["claim_id"])],
                "rag": rag,
                "memory": memory,
                "router": router_output["derived_prediction"],
                "targeted_stage_c": treatment_prediction,
                "generic_control": control_prediction,
                "endpoint_disagreement": disagreement,
                "targeted_selected_endpoint": treatment_endpoint,
                "generic_selected_endpoint": control_endpoint,
                "pivotal_proposition": proposition,
                "proposition_basis": proposition_basis,
                "generic_fallback": proposition_fallback,
            }
        )
    rows.sort(key=lambda row: (row["condition_id"], row["claim_id"]))
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    systems = ("rag", "memory", "router", "generic_control", "targeted_stage_c")
    disagreements = [row for row in rows if row["endpoint_disagreement"]]
    return {
        "pairs": len(rows),
        "disagreements": len(disagreements),
        "activation_rate": len(disagreements) / len(rows) if rows else None,
        "systems": {field: metrics(rows, field) for field in systems},
        "paired": {
            "targeted_vs_memory": paired(rows, "targeted_stage_c", "memory"),
            "targeted_vs_rag": paired(rows, "targeted_stage_c", "rag"),
            "targeted_vs_router": paired(rows, "targeted_stage_c", "router"),
            "targeted_vs_generic": paired(rows, "targeted_stage_c", "generic_control"),
        },
        "selected_endpoints_on_disagreements": {
            "targeted": dict(
                sorted(Counter(row["targeted_selected_endpoint"] for row in disagreements).items())
            ),
            "generic": dict(
                sorted(Counter(row["generic_selected_endpoint"] for row in disagreements).items())
            ),
        },
        "targeted_proposition_basis": dict(
            sorted(Counter(row["proposition_basis"] for row in disagreements).items())
        ),
        "generic_fallbacks": sum(row["generic_fallback"] for row in disagreements),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=Path("artifacts/evaluation/stage1_labels.json"))
    parser.add_argument(
        "--cache-root", type=Path, default=Path("artifacts/cache/llm")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/evaluation/stage4_final_study.json")
    )
    args = parser.parse_args()
    labels = json.loads(args.labels.read_text(encoding="utf-8"))["development"]
    specifications = {
        "method_design": (
            Path("artifacts/runs/stage3/stage3_same_model_ab_v1"),
            Path("artifacts/runs/stage4/stage4_same_model_c_v1"),
            Path("artifacts/runs/stage4/stage4_generic_control_design_v1"),
        ),
        "development_validation": (
            Path("artifacts/runs/stage3/stage3_same_model_validation_v1"),
            Path("artifacts/runs/stage4/stage4_same_model_validation_v1"),
            Path("artifacts/runs/stage4/stage4_generic_control_validation_v1"),
        ),
    }
    all_rows: list[dict[str, Any]] = []
    by_split: dict[str, Any] = {}
    call_accounting: dict[str, Any] = {}
    split_claims: dict[str, set[int]] = {}
    for split, (router_root, treatment_root, control_root) in specifications.items():
        router_input = manifest(router_root)
        treatment_input = manifest(treatment_root)
        control_input = manifest(control_root)
        rows = assemble(
            split=split,
            router_manifest=router_input,
            treatment_manifest=treatment_input,
            control_manifest=control_input,
            labels=labels,
        )
        split_claims[split] = {row["claim_id"] for row in rows}
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[row["condition_id"]].append(row)
        by_split[split] = {
            condition: summarize(group) for condition, group in sorted(grouped.items())
        }
        router_keys = [
            row["cache_key"]
            for row in router_input["outputs"]
            if row["victim_model_id"] == "llama31_70b"
            and row["variant"] == "endpoint_only"
            and row["condition_id"] in ("clean", "fact2fiction_p0.01")
        ]
        treatment_rows = [
            row
            for row in treatment_input["outputs"]
            if row["victim_model_id"] == "llama31_70b"
            and row["condition_id"] in ("clean", "fact2fiction_p0.01")
        ]
        control_rows = [
            row
            for row in control_input["outputs"]
            if row["victim_model_id"] == "llama31_70b"
            and row["condition_id"] in ("clean", "fact2fiction_p0.01")
        ]
        treatment_check_keys = [row["proposition_cache_key"] for row in treatment_rows]
        treatment_final_keys = [row["final_cache_key"] for row in treatment_rows]
        control_check_keys = [row["proposition_cache_key"] for row in control_rows]
        control_final_keys = [row["final_cache_key"] for row in control_rows]
        call_accounting[split] = {
            "targeted_semantic_calls": len(router_keys)
            + len(treatment_check_keys)
            + len(treatment_final_keys),
            "generic_control_semantic_calls": len(router_keys)
            + len(control_check_keys)
            + len(control_final_keys),
            "targeted": {
                "router": cache_usage(args.cache_root, router_keys),
                "proposition_check": cache_usage(args.cache_root, treatment_check_keys),
                "final_selector": cache_usage(args.cache_root, treatment_final_keys),
            },
            "generic_control": {
                "shared_router": cache_usage(args.cache_root, router_keys),
                "generic_check": cache_usage(args.cache_root, control_check_keys),
                "final_selector": cache_usage(args.cache_root, control_final_keys),
            },
        }
        all_rows.extend(rows)
    if split_claims["method_design"] & split_claims["development_validation"]:
        raise ValueError("Design and validation claim groups overlap")
    pooled: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_rows:
        pooled[row["condition_id"]].append(row)
    pooled_summary = {condition: summarize(group) for condition, group in sorted(pooled.items())}
    result = {
        "summary_schema_version": 1,
        "method": "frozen same-model endpoint-only Stage C",
        "model": "llama31_70b",
        "attack_condition": "fact2fiction_p0.01",
        "warning": (
            "Method-design selected the frozen treatment. Development-validation was joined once "
            "after inference/audits. The generic control was added post-validation as a fixed "
            "ablation and was not used to modify the treatment."
        ),
        "by_split": by_split,
        "pooled_development": pooled_summary,
        "call_accounting": call_accounting,
        "validation_primary_claim": {
            "outperforms_same_model_memory_at_1pct": (
                by_split["development_validation"]["fact2fiction_p0.01"]["systems"][
                    "targeted_stage_c"
                ]["accuracy"]
                > by_split["development_validation"]["fact2fiction_p0.01"]["systems"]["memory"][
                    "accuracy"
                ]
            ),
            "outperforms_poisoned_rag_at_1pct": (
                by_split["development_validation"]["fact2fiction_p0.01"]["systems"][
                    "targeted_stage_c"
                ]["accuracy"]
                > by_split["development_validation"]["fact2fiction_p0.01"]["systems"]["rag"][
                    "accuracy"
                ]
            ),
            "outperforms_exact_budget_generic_control_at_1pct": (
                by_split["development_validation"]["fact2fiction_p0.01"]["systems"][
                    "targeted_stage_c"
                ]["accuracy"]
                > by_split["development_validation"]["fact2fiction_p0.01"]["systems"]
                ["generic_control"]["accuracy"]
            ),
            "clean_examples_below_rag": (
                by_split["development_validation"]["clean"]["systems"]["rag"]["correct"]
                - by_split["development_validation"]["clean"]["systems"]["targeted_stage_c"][
                    "correct"
                ]
            ),
        },
        "disagreement_case_rows": [row for row in all_rows if row["endpoint_disagreement"]],
    }
    atomic_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
