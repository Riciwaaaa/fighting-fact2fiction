#!/usr/bin/env python3
"""Build attacker-hidden, same-model held-out inputs for the frozen Stage 5 workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from build_stage2_packets import internal_lookup
from parametric_rag_defense.aligned_workflow import build_aligned_packet
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import canonical_json
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.stage2_packets import build_packet, store_immutable as store_source_packet
from parametric_rag_defense.workflow_runtime import store_immutable_output

MODELS = ("glm52", "llama31_70b", "qwen35_35b_a3b")
ATTACK_CONDITIONS = {
    "glm52": "cross_glm52_p001",
    "llama31_70b": "cross_llama31_70b_p001",
    "qwen35_35b_a3b": "cross_qwen35_35b_a3b_p001",
}
INTERNAL_FALLBACK_PATH = Path("configs/stage5_locked_confirmation_amendment_2.json")


def apply_fail_closed_internal_resolution(
    samples: dict[str, dict[int, list[dict[str, Any]]]],
    cache_keys: dict[str, dict[int, list[str]]],
    internal_root: Path,
) -> dict[str, Any]:
    """Resolve only the explicitly recorded all-retries-invalid endpoint as an abstention."""

    amendment = json.loads(INTERNAL_FALLBACK_PATH.read_text(encoding="utf-8"))
    resolution = amendment["fail_closed_resolution"]
    model_id = str(resolution["model_id"])
    claim_id = int(resolution["claim_id"])
    seeds = [int(value) for value in resolution["seeds"]]
    manifest = json.loads((internal_root / f"{model_id}.json").read_text(encoding="utf-8"))
    rows = sorted(
        (
            row
            for row in manifest["outputs"]
            if int(row["claim_id"]) == claim_id
        ),
        key=lambda row: int(row["seed"]),
    )
    if [int(row["seed"]) for row in rows] != seeds or any(
        row.get("contract_ok") for row in rows
    ):
        raise ValueError("recorded fail-closed internal resolution does not match raw failures")
    fallback = dict(resolution["synthetic_abstention"])
    samples[model_id][claim_id] = [dict(fallback) for _ in rows]
    cache_keys[model_id][claim_id] = [str(row["cache_key"]) for row in rows]
    return {
        "policy": "all_retries_invalid_to_abstention",
        "amendment_path": str(INTERNAL_FALLBACK_PATH),
        "model_id": model_id,
        "claim_id": claim_id,
        "seeds": seeds,
        "failed_final_cache_keys": list(cache_keys[model_id][claim_id]),
        "sensitivity_required": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1-config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--clean-manifest",
        type=Path,
        default=Path(
            "artifacts/runs/stage1/locked_test/rag/stage1_locked_confirm_v1/"
            "manifests/clean_manifest.json"
        ),
    )
    parser.add_argument(
        "--clean-endpoint-root",
        type=Path,
        default=Path(
            "artifacts/runs/stage1/locked_test/rag/stage1_locked_confirm_v1/endpoints"
        ),
    )
    parser.add_argument(
        "--cross-manifest",
        type=Path,
        default=Path(
            "artifacts/runs/stage1/locked_test/rag/stage1_locked_crossed_1pct_v1/"
            "manifests/crossed_manifest.json"
        ),
    )
    parser.add_argument("--experiment-id", default="stage3_locked_neutral_inputs_v1")
    parser.add_argument("--allow-locked-test", action="store_true")
    args = parser.parse_args()
    if not args.allow_locked_test:
        raise SystemExit("Refusing to build locked inputs without --allow-locked-test")

    config = json.loads(args.stage1_config.read_text(encoding="utf-8"))
    dataset = json.loads(Path(config["dataset"]["source"]).read_text(encoding="utf-8"))
    split = json.loads(Path(config["dataset"]["split_manifest"]).read_text(encoding="utf-8"))
    locked_ids = set(int(value) for value in split["locked_test"]["claim_ids"])
    internal_root = Path("artifacts/runs/stage1/locked_test/internal_endpoint")
    samples, cache_keys = internal_lookup(config, internal_root, Path(config["cache_root"]))
    internal_resolution = apply_fail_closed_internal_resolution(
        samples, cache_keys, internal_root
    )
    if set(samples) != set(MODELS):
        raise ValueError(f"unexpected internal model set: {sorted(samples)}")
    for model_id in MODELS:
        if set(samples[model_id]) != locked_ids:
            raise ValueError(f"locked internal coverage mismatch for {model_id}")

    clean_manifest = json.loads(args.clean_manifest.read_text(encoding="utf-8"))
    cross_manifest = json.loads(args.cross_manifest.read_text(encoding="utf-8"))
    if clean_manifest["failures"] or len(clean_manifest["successes"]) != 300:
        raise ValueError("locked clean manifest is incomplete")
    common_claims = set(int(value) for value in cross_manifest["common_claim_ids"])
    if (
        cross_manifest["failures"]
        or cross_manifest["requested"] != 9 * len(common_claims)
        or len(cross_manifest["successes"]) != 9 * len(common_claims)
    ):
        raise ValueError("locked crossed manifest is incomplete")

    output_root = Path("artifacts/runs/stage3") / args.experiment_id
    source_packet_root = Path("artifacts/runs/stage2/stage2_locked_neutral_inputs_v1/packets")
    aligned_packet_root = output_root / "packets" / "endpoint_only"
    ledger = ExperimentLedger(
        Path("artifacts/runs/progress"),
        args.experiment_id,
        description="Attacker-hidden locked Stage 5 input construction",
    )
    expected = 300 + 9 * len(common_claims)
    ledger.update(
        status="running",
        phase="packet_build",
        event="locked_neutral_input_build_started",
        counts={"expected": expected, "completed": 0},
        details={"jointly_eligible_claims": len(common_claims)},
    )

    descriptors: list[dict[str, Any]] = []

    def add_endpoint(
        endpoint: dict[str, Any],
        *,
        victim_model_id: str,
        condition_id: str,
        attacker_model_id: str | None,
    ) -> None:
        claim_id = int(endpoint["task"]["claim_id"])
        if claim_id not in locked_ids or victim_model_id not in MODELS:
            raise ValueError("endpoint lies outside the locked same-model scope")
        source_packet = build_packet(
            claim_id=claim_id,
            claim=dataset[claim_id]["claim"],
            claim_date=dataset[claim_id].get("claim_date") or "unknown",
            rag_task_key=endpoint["task_key"],
            rag_judgment=endpoint["judgment"],
            internal_samples={model_id: samples[model_id][claim_id] for model_id in MODELS},
            internal_cache_keys={model_id: cache_keys[model_id][claim_id] for model_id in MODELS},
        )
        source_path, _ = store_source_packet(source_packet_root, source_packet)
        aligned = build_aligned_packet(
            source_packet=source_packet,
            rag_judgment=endpoint["judgment"],
            model_id=victim_model_id,
            variant="endpoint_only",
        )
        aligned_path, _ = store_immutable_output(
            aligned_packet_root, aligned["packet_key"], aligned
        )
        descriptors.append(
            {
                "claim_id": claim_id,
                "partition": "locked_test",
                "victim_model_id": victim_model_id,
                "condition_id": condition_id,
                "attacker_model_id": attacker_model_id,
                "variant": "endpoint_only",
                "source_packet_key": source_packet["packet_key"],
                "source_packet_path": str(source_path),
                "aligned_packet_key": aligned["packet_key"],
                "aligned_packet_path": str(aligned_path),
                "rag_task_key": endpoint["task_key"],
            }
        )

    for row in clean_manifest["successes"]:
        path = (
            args.clean_endpoint_root
            / str(row["task_key"])[:2]
            / f"{row['task_key']}.json"
        )
        endpoint = json.loads(path.read_text(encoding="utf-8"))
        add_endpoint(
            endpoint,
            victim_model_id=str(row["model_id"]),
            condition_id="clean",
            attacker_model_id=None,
        )
    for row in cross_manifest["successes"]:
        attacker = str(row["attacker_model_id"])
        add_endpoint(
            json.loads(Path(row["artifact_path"]).read_text(encoding="utf-8")),
            victim_model_id=str(row["victim_model_id"]),
            condition_id=ATTACK_CONDITIONS[attacker],
            attacker_model_id=attacker,
        )

    descriptors.sort(
        key=lambda row: (row["claim_id"], row["victim_model_id"], row["condition_id"])
    )
    identities = {
        (row["claim_id"], row["victim_model_id"], row["condition_id"])
        for row in descriptors
    }
    if len(descriptors) != expected or len(identities) != expected:
        raise ValueError(
            f"locked input identity mismatch: rows={len(descriptors)} unique={len(identities)}"
        )
    condition_counts = Counter(row["condition_id"] for row in descriptors)
    victim_counts = Counter(row["victim_model_id"] for row in descriptors)
    private_index = {
        "warning": "PRIVATE: attacker identity and condition never enter an LLM prompt",
        "experiment_id": args.experiment_id,
        "split": "locked_test",
        "internal_resolution": internal_resolution,
        "rows": descriptors,
    }
    index_digest = hashlib.sha256(canonical_json(private_index).encode()).hexdigest()
    atomic_json(output_root / "private_index.json", private_index)
    manifest = {
        "manifest_schema_version": 1,
        "experiment_id": args.experiment_id,
        "split": "locked_test",
        "dry_run": False,
        "failures": [],
        "expected": expected,
        "common_claim_ids": sorted(common_claims),
        "internal_resolution": internal_resolution,
        "outputs": descriptors,
        "condition_counts": dict(sorted(condition_counts.items())),
        "victim_counts": dict(sorted(victim_counts.items())),
        "private_index_sha256": index_digest,
        "note": "Input-only router-compatible manifest; no Stage 3 router call is used by Stage 5.",
    }
    atomic_json(output_root / "private_manifest.json", manifest)
    atomic_json(
        output_root / "manifest.json",
        {
            key: value
            for key, value in manifest.items()
            if key not in {"outputs", "common_claim_ids"}
        },
    )
    ledger.update(
        status="complete",
        phase="packet_build",
        event="locked_neutral_input_build_completed",
        counts={"expected": expected, "completed": len(descriptors)},
        artifacts={"private_manifest": str(output_root / "private_manifest.json")},
        details={"private_index_sha256": index_digest},
    )
    print(
        json.dumps(
            {
                "status": "complete",
                "inputs": len(descriptors),
                "clean": condition_counts["clean"],
                "crossed": len(descriptors) - condition_counts["clean"],
                "jointly_eligible_claims": len(common_claims),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
