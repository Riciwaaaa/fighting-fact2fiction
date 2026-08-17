#!/usr/bin/env python3
"""Build sanitized Stage 2/3 packets from immutable Stage 1 endpoint caches."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import canonical_json
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.stage2_packets import build_packet, store_immutable


def load_cache_entry(cache_root: Path, key: str) -> dict[str, Any]:
    path = cache_root / "entries" / key[:2] / f"{key}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("key") != key or not value.get("response", {}).get("contract_ok"):
        raise ValueError(f"Invalid internal cache entry: {path}")
    parsed = value["response"].get("parsed")
    if not isinstance(parsed, dict):
        raise ValueError(f"Internal cache entry has no parsed judgment: {path}")
    return value


def internal_lookup(
    config: dict[str, Any], manifest_root: Path, cache_root: Path
) -> tuple[dict[str, dict[int, list[dict[str, Any]]]], dict[str, dict[int, list[str]]]]:
    samples: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    keys: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    expected_seeds = sorted(config["decoding"]["internal"]["seeds"])
    for model in config["models"]:
        if not model.get("enabled") or "internal" not in model["roles"]:
            continue
        model_id = model["id"]
        manifest_path = manifest_root / f"{model_id}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("failures"):
            raise ValueError(f"Active internal manifest has failures: {manifest_path}")
        descriptors: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for output in manifest["outputs"]:
            if output.get("contract_ok"):
                descriptors[int(output["claim_id"])].append(output)
        for claim_id, rows in descriptors.items():
            rows.sort(key=lambda row: int(row["seed"]))
            found_seeds = [int(row["seed"]) for row in rows]
            if found_seeds != expected_seeds:
                raise ValueError(
                    f"Internal seed mismatch model={model_id} claim={claim_id}: {found_seeds}"
                )
            for row in rows:
                key = str(row["cache_key"])
                entry = load_cache_entry(cache_root, key)
                metadata = entry.get("metadata", {})
                if (
                    metadata.get("role") != "internal_endpoint"
                    or metadata.get("model_id") != model_id
                    or int(metadata.get("claim_id")) != claim_id
                ):
                    raise ValueError(f"Internal cache metadata mismatch for {key}")
                samples[model_id][claim_id].append(entry["response"]["parsed"])
                keys[model_id][claim_id].append(key)
    return samples, keys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1-config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--workflow-config", type=Path, default=Path("configs/stage234_workflow.json")
    )
    parser.add_argument(
        "--split", type=Path, default=Path("configs/splits/stage234_development.json")
    )
    parser.add_argument("--eligibility", type=Path)
    parser.add_argument(
        "--partition",
        choices=("method_design", "development_validation", "all"),
        default="method_design",
    )
    parser.add_argument("--experiment-id", default="stage2_signal_v1")
    args = parser.parse_args()

    stage1_config = json.loads(args.stage1_config.read_text(encoding="utf-8"))
    workflow_config = json.loads(args.workflow_config.read_text(encoding="utf-8"))
    split = json.loads(args.split.read_text(encoding="utf-8"))
    namespace = stage1_config["rag_pipeline"]["artifact_namespace"]
    args.eligibility = args.eligibility or Path(
        f"artifacts/evaluation/{namespace}_clean_eligibility.json"
    )
    root = Path("artifacts/runs/stage2") / args.experiment_id
    packet_root = root / "packets"
    rag_root = Path("artifacts/runs/stage1/development/rag") / namespace / "endpoints"
    internal_root = Path("artifacts/runs/stage1/development/internal_endpoint")
    cache_root = Path(stage1_config["cache_root"])
    dataset_path = Path(stage1_config["dataset"]["source"])
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    ledger = ExperimentLedger(
        Path("artifacts/runs/progress"),
        args.experiment_id,
        description="Gold-isolated Stage 2 characterization and sanitized packet construction",
    )

    partitions = {
        "method_design": set(int(value) for value in split["method_design"]["claim_ids"]),
        "development_validation": set(
            int(value) for value in split["development_validation"]["claim_ids"]
        ),
    }
    selected_ids = set().union(*partitions.values()) if args.partition == "all" else partitions[args.partition]
    eligibility = json.loads(args.eligibility.read_text(encoding="utf-8"))
    conditions = list(workflow_config["stage2"]["conditions"])
    victim_model_ids = sorted(
        model["id"]
        for model in stage1_config["models"]
        if model.get("enabled") and "rag_victim" in model["roles"]
    )
    expected_tasks: set[tuple[str, int, str]] = set()
    for victim_model_id in victim_model_ids:
        eligible_ids = set(
            int(value)
            for value in eligibility["models"][victim_model_id]["eligible_claim_ids"]
        )
        for claim_id in selected_ids:
            expected_tasks.add((victim_model_id, claim_id, "clean"))
            if claim_id in eligible_ids:
                expected_tasks.update(
                    (victim_model_id, claim_id, condition)
                    for condition in conditions
                    if condition != "clean"
                )
    ledger.update(
        status="running",
        phase="packet_build",
        event="packet_build_started",
        counts={"selected_claims": len(selected_ids), "packets_completed": 0},
        details={"source_namespace": namespace, "partition": args.partition},
    )

    samples, cache_keys = internal_lookup(stage1_config, internal_root, cache_root)
    internal_model_ids = sorted(samples)
    expected_claims = set(split["method_design"]["claim_ids"]) | set(
        split["development_validation"]["claim_ids"]
    )
    for model_id in internal_model_ids:
        missing = expected_claims - set(samples[model_id])
        if missing:
            raise ValueError(f"Internal model {model_id} is missing claims: {sorted(missing)}")

    rows: list[dict[str, Any]] = []
    condition_counts: Counter[str] = Counter()
    victim_counts: Counter[str] = Counter()
    cached_count = 0
    endpoint_paths = sorted(rag_root.glob("*/*.json"))
    for path in endpoint_paths:
        endpoint = json.loads(path.read_text(encoding="utf-8"))
        task = endpoint["task"]
        claim_id = int(task["claim_id"])
        if claim_id not in selected_ids:
            continue
        model_id = str(task["model_id"])
        condition_id = str(task["condition"]["id"])
        if condition_id not in conditions:
            continue
        partition = (
            "method_design" if claim_id in partitions["method_design"] else "development_validation"
        )
        packet = build_packet(
            claim_id=claim_id,
            claim=dataset[claim_id]["claim"],
            claim_date=dataset[claim_id].get("claim_date") or "unknown",
            rag_task_key=endpoint["task_key"],
            rag_judgment=endpoint["judgment"],
            internal_samples={
                internal_model_id: samples[internal_model_id][claim_id]
                for internal_model_id in internal_model_ids
            },
            internal_cache_keys={
                internal_model_id: cache_keys[internal_model_id][claim_id]
                for internal_model_id in internal_model_ids
            },
        )
        packet_path, cached = store_immutable(packet_root, packet)
        cached_count += int(cached)
        rows.append(
            {
                "packet_key": packet["packet_key"],
                "packet_path": str(packet_path),
                "rag_task_key": endpoint["task_key"],
                "claim_id": claim_id,
                "partition": partition,
                "victim_model_id": model_id,
                "condition_id": condition_id,
            }
        )
        condition_counts[condition_id] += 1
        victim_counts[model_id] += 1
        if len(rows) % 50 == 0:
            ledger.update(
                status="running",
                phase="packet_build",
                event="packet_build_progress",
                counts={"selected_claims": len(selected_ids), "packets_completed": len(rows)},
            )

    rows.sort(key=lambda row: (row["claim_id"], row["victim_model_id"], row["condition_id"]))
    unique_task_keys = {row["rag_task_key"] for row in rows}
    unique_packet_keys = {row["packet_key"] for row in rows}
    if len(unique_task_keys) != len(rows) or len(unique_packet_keys) != len(rows):
        raise ValueError("Stage 2 packet index contains duplicate task or packet keys")
    if not rows:
        raise ValueError("No Stage 2 packets were built")
    observed_tasks = {
        (row["victim_model_id"], int(row["claim_id"]), row["condition_id"]) for row in rows
    }
    if observed_tasks != expected_tasks:
        raise ValueError(
            "Stage 2 endpoint completeness mismatch; "
            f"missing={len(expected_tasks-observed_tasks)}, "
            f"unexpected={len(observed_tasks-expected_tasks)}"
        )

    private_index = {
        "warning": "PRIVATE ROUTING/EVALUATION INDEX: never serialize this object into an LLM prompt",
        "experiment_id": args.experiment_id,
        "partition_request": args.partition,
        "rows": rows,
    }
    index_digest = hashlib.sha256(canonical_json(private_index).encode()).hexdigest()
    atomic_json(root / "private_index.json", private_index)
    manifest = {
        "manifest_schema_version": 1,
        "experiment_id": args.experiment_id,
        "source_namespace": namespace,
        "packet_schema_version": workflow_config["stage2"]["packet_schema_version"],
        "partition_request": args.partition,
        "selected_claim_count": len(selected_ids),
        "expected_packet_count": len(expected_tasks),
        "packet_count": len(rows),
        "existing_packet_count": cached_count,
        "condition_counts": dict(sorted(condition_counts.items())),
        "victim_counts": dict(sorted(victim_counts.items())),
        "private_index_sha256": index_digest,
        "inference_contract": "Only each packet's visible object may be serialized into model messages.",
    }
    atomic_json(root / "manifest.json", manifest)
    ledger.update(
        status="complete",
        phase="packet_build",
        event="packet_build_completed",
        counts={"selected_claims": len(selected_ids), "packets_completed": len(rows)},
        artifacts={"manifest": str(root / "manifest.json")},
        details={"private_index_sha256": index_digest},
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
