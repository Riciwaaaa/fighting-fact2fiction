#!/usr/bin/env python3
"""Audit held-out internal, clean/crossed RAG, and attacker-hidden Stage 5 inputs."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from parametric_rag_defense.cache import canonical_json

MODELS = ("glm52", "llama31_70b", "qwen35_35b_a3b")
_URL = re.compile(r"https?://", re.IGNORECASE)
_ORIGIN = re.compile(r"\b(?:clean|poison):\d+\b", re.IGNORECASE)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--clean-manifest",
        type=Path,
        default=Path(
            "artifacts/runs/stage1/locked_test/rag/stage1_locked_confirm_v1/"
            "manifests/clean_manifest.json"
        ),
    )
    parser.add_argument(
        "--clean-root",
        type=Path,
        default=Path("artifacts/runs/stage1/locked_test/rag/stage1_locked_confirm_v1"),
    )
    parser.add_argument(
        "--eligibility",
        type=Path,
        default=Path("artifacts/evaluation/stage1_locked_confirm_v1_clean_eligibility.json"),
    )
    parser.add_argument(
        "--cross-manifest",
        type=Path,
        default=Path(
            "artifacts/runs/stage1/locked_test/rag/stage1_locked_crossed_1pct_v1/"
            "manifests/crossed_manifest.json"
        ),
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=Path("artifacts/runs/stage3/stage3_locked_neutral_inputs_v1"),
    )
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    split = json.loads(Path(config["dataset"]["split_manifest"]).read_text(encoding="utf-8"))
    locked_ids = set(int(value) for value in split["locked_test"]["claim_ids"])
    model_names = {
        model["id"]: model["model"]
        for model in config["models"]
        if model.get("enabled") and model["id"] in MODELS
    }
    cache_root = Path(config["cache_root"])
    failures: list[str] = []
    inspected_cache_keys: set[str] = set()

    amendment = json.loads(
        Path("configs/stage5_locked_confirmation_amendment_2.json").read_text(
            encoding="utf-8"
        )
    )
    resolution = amendment["fail_closed_resolution"]
    fallback_model = str(resolution["model_id"])
    fallback_claim = int(resolution["claim_id"])
    fallback_seeds = set(int(value) for value in resolution["seeds"])
    observed_invalid_internal: set[tuple[str, int, int]] = set()

    internal_root = Path("artifacts/runs/stage1/locked_test/internal_endpoint")
    for model_id in MODELS:
        manifest = json.loads((internal_root / f"{model_id}.json").read_text(encoding="utf-8"))
        expected_pairs = {(claim_id, seed) for claim_id in locked_ids for seed in (11, 29, 47)}
        actual_pairs = {
            (int(row["claim_id"]), int(row["seed"])) for row in manifest.get("outputs", [])
        }
        if manifest.get("failures") or actual_pairs != expected_pairs:
            failures.append(f"internal manifest coverage/failure mismatch for {model_id}")
        for row in manifest.get("outputs", []):
            if row.get("contract_ok"):
                continue
            identity = (model_id, int(row["claim_id"]), int(row["seed"]))
            observed_invalid_internal.add(identity)
            try:
                if identity != (fallback_model, fallback_claim, identity[2]):
                    raise ValueError("unregistered invalid internal output")
                if identity[2] not in fallback_seeds or row.get("contract_retry_count") != 3:
                    raise ValueError("fallback seed/retry count mismatch")
                if len(row.get("attempts", [])) != 4 or any(
                    attempt.get("contract_ok") for attempt in row["attempts"]
                ):
                    raise ValueError("fallback attempts are not four retained failures")
                for attempt in row["attempts"]:
                    key = str(attempt["cache_key"])
                    entry = json.loads(
                        (cache_root / "entries" / key[:2] / f"{key}.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    if (
                        entry["request"]["model"] != model_names[model_id]
                        or entry["response"].get("contract_ok")
                        or entry["response"].get("finish_reason") != "length"
                    ):
                        raise ValueError("fallback cache attempt identity/status mismatch")
            except Exception as exc:
                failures.append(f"internal fallback {identity}: {exc}")
    expected_invalid_internal = {
        (fallback_model, fallback_claim, seed) for seed in fallback_seeds
    }
    if observed_invalid_internal != expected_invalid_internal:
        failures.append("invalid internal output set differs from the recorded fallback")

    def audit_receipt(key: str, victim_id: str, role: str) -> None:
        path = cache_root / "entries" / key[:2] / f"{key}.json"
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry["key"] != key or entry["request"]["model"] != model_names[victim_id]:
            raise ValueError(f"{role} cache identity/model mismatch")
        messages = canonical_json(entry["request"]["messages"])
        if _URL.search(messages) or _ORIGIN.search(messages):
            raise ValueError(f"{role} prompt leaks source origin")
        lowered = messages.lower()
        for marker in (
            "attacker_model_id",
            "victim_model_id",
            "cross_glm52",
            "cross_llama31",
            "cross_qwen35",
            "gold_label",
        ):
            if marker in lowered:
                raise ValueError(f"{role} prompt leaks experimental marker {marker}")
        inspected_cache_keys.add(key)

    clean_manifest = json.loads(args.clean_manifest.read_text(encoding="utf-8"))
    clean_rows = clean_manifest.get("successes", [])
    if clean_manifest.get("failures") or len(clean_rows) != 300:
        failures.append("clean manifest is not complete at 300 rows")
    clean_cells: Counter[str] = Counter()
    clean_identities = set()
    for row in clean_rows:
        identity = (row["model_id"], int(row["claim_id"]))
        if identity in clean_identities:
            failures.append(f"duplicate clean identity: {identity}")
        clean_identities.add(identity)
        clean_cells[row["model_id"]] += 1
        try:
            task_key = str(row["task_key"])
            endpoint = json.loads(
                (
                    args.clean_root / "endpoints" / task_key[:2] / f"{task_key}.json"
                ).read_text(encoding="utf-8")
            )
            trace = json.loads(
                (
                    args.clean_root / "private_traces" / task_key[:2] / f"{task_key}.json"
                ).read_text(encoding="utf-8")
            )
            task = endpoint["task"]
            if (
                int(task["claim_id"]) not in locked_ids
                or task["split"] != "locked_test"
                or task["condition"]["id"] != "clean"
                or task["model_id"] != row["model_id"]
                or endpoint["audit"]["poison_documents_injected"] != 0
            ):
                raise ValueError("clean endpoint identity or zero-poison invariant failed")
            for role, receipts in trace["llm_receipts"].items():
                for receipt in receipts:
                    audit_receipt(receipt["cache_key"], row["model_id"], f"clean {role}")
        except Exception as exc:
            failures.append(f"clean {identity}: {exc}")
    for model_id in MODELS:
        if clean_cells[model_id] != 100:
            failures.append(f"clean cell {model_id} has {clean_cells[model_id]} rows")

    eligibility = json.loads(args.eligibility.read_text(encoding="utf-8"))
    if eligibility.get("split") != "locked_test":
        failures.append("eligibility split is not locked_test")
    eligible_sets = {
        model_id: set(eligibility["models"][model_id]["eligible_claim_ids"])
        for model_id in MODELS
    }
    common_claims = set.intersection(*eligible_sets.values())
    if not common_claims or not common_claims <= locked_ids:
        failures.append("joint eligibility scope is empty or outside locked IDs")

    cross_manifest = json.loads(args.cross_manifest.read_text(encoding="utf-8"))
    cross_rows = cross_manifest.get("successes", [])
    expected_cross = 9 * len(common_claims)
    if (
        cross_manifest.get("split") != "locked_test"
        or cross_manifest.get("failures")
        or set(cross_manifest.get("common_claim_ids", [])) != common_claims
        or cross_manifest.get("requested") != expected_cross
        or len(cross_rows) != expected_cross
    ):
        failures.append("crossed manifest scope or coverage mismatch")
    crossed_cells: Counter[tuple[str, str]] = Counter()
    crossed_identities = set()
    for row in cross_rows:
        identity = (
            row["attacker_model_id"],
            row["victim_model_id"],
            int(row["claim_id"]),
        )
        if identity in crossed_identities:
            failures.append(f"duplicate crossed identity: {identity}")
        crossed_identities.add(identity)
        crossed_cells[identity[:2]] += 1
        try:
            endpoint = json.loads(Path(row["artifact_path"]).read_text(encoding="utf-8"))
            trace = json.loads(Path(row["trace_path"]).read_text(encoding="utf-8"))
            task = endpoint["task"]
            if (
                int(task["claim_id"]) != identity[2]
                or task["split"] != "locked_test"
                or task["condition"]["id"] != "fact2fiction_p0.01"
                or task["attacker_model_id"] != identity[0]
                or task["victim_model_id"] != identity[1]
                or task["model_id"] != identity[1]
            ):
                raise ValueError("crossed task identity mismatch")
            provenance = endpoint["provenance"]
            if (
                provenance["attack_generator_model_id"] != identity[0]
                or provenance["victim_model_id"] != identity[1]
            ):
                raise ValueError("crossed provenance mismatch")
            material = json.loads(
                Path(trace["source_poison_material"]).read_text(encoding="utf-8")
            )
            if (
                material["model_id"] != identity[0]
                or material["documents_sha256"]
                != provenance["source_poison_documents_sha256"]
            ):
                raise ValueError("crossed poison-source mismatch")
            for role, receipts in trace["llm_receipts"].items():
                for receipt in receipts:
                    audit_receipt(receipt["cache_key"], identity[1], f"crossed {role}")
        except Exception as exc:
            failures.append(f"crossed {identity}: {exc}")
    for attacker in MODELS:
        for victim in MODELS:
            if crossed_cells[(attacker, victim)] != len(common_claims):
                failures.append(
                    f"crossed cell {attacker}/{victim} has "
                    f"{crossed_cells[(attacker, victim)]} rows"
                )

    input_manifest = json.loads(
        (args.input_root / "private_manifest.json").read_text(encoding="utf-8")
    )
    manifest_resolution = input_manifest.get("internal_resolution", {})
    if (
        manifest_resolution.get("model_id") != fallback_model
        or manifest_resolution.get("claim_id") != fallback_claim
        or set(manifest_resolution.get("seeds", [])) != fallback_seeds
    ):
        failures.append("Stage 5 input manifest omits or changes the internal resolution")
    input_rows = input_manifest.get("outputs", [])
    expected_inputs = 300 + expected_cross
    if (
        input_manifest.get("split") != "locked_test"
        or input_manifest.get("failures")
        or input_manifest.get("expected") != expected_inputs
        or len(input_rows) != expected_inputs
    ):
        failures.append("Stage 5 input manifest scope or coverage mismatch")
    input_identities = set()
    for row in input_rows:
        identity = (row["claim_id"], row["victim_model_id"], row["condition_id"])
        if identity in input_identities:
            failures.append(f"duplicate Stage 5 input: {identity}")
        input_identities.add(identity)
        try:
            packet = json.loads(Path(row["aligned_packet_path"]).read_text(encoding="utf-8"))
            if (
                packet["packet_key"] != row["aligned_packet_key"]
                or packet["provenance"]["same_model_id"] != row["victim_model_id"]
            ):
                raise ValueError("aligned packet identity/same-model mismatch")
            if row["victim_model_id"] == fallback_model and row["claim_id"] == fallback_claim:
                memory = packet["visible"]["memory_only_assessment"]
                expected_abstention = resolution["synthetic_abstention"]
                if (
                    memory["leading_verdicts"] != ["Not Enough Evidence"]
                    or memory["repeat_count"] != 3
                    or memory["samples"] != [expected_abstention] * 3
                ):
                    raise ValueError("fail-closed memory endpoint is not the recorded abstention")
            serialized = canonical_json(packet)
            for marker in (
                "attacker_model_id",
                "condition_id",
                "fact2fiction_p",
                "cross_glm52",
                "cross_llama31",
                "cross_qwen35",
                "gold_label",
            ):
                if marker in serialized.lower():
                    raise ValueError(f"aligned packet leaks {marker}")
        except Exception as exc:
            failures.append(f"input {identity}: {exc}")

    result = {
        "split": "locked_test",
        "clean_outputs": len(clean_rows),
        "jointly_eligible_claims": len(common_claims),
        "crossed_outputs": len(cross_rows),
        "stage5_inputs": len(input_rows),
        "inspected_unique_victim_cache_entries": len(inspected_cache_keys),
        "invalid_internal_outputs_resolved_fail_closed": len(observed_invalid_internal),
        "clean_cell_counts": dict(sorted(clean_cells.items())),
        "crossed_cell_counts": {
            f"{attacker}->{victim}": crossed_cells[(attacker, victim)]
            for attacker in MODELS
            for victim in MODELS
        },
        "validation_failures": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
