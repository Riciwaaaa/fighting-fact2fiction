#!/usr/bin/env python3
"""Build attacker-hidden packets and a combined endpoint namespace for crossed Stage C."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from build_stage2_packets import internal_lookup
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import canonical_json
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.matrix import task_key
from parametric_rag_defense.rag_artifacts import normalize_record, store_immutable as store_endpoint
from parametric_rag_defense.stage2_packets import build_packet, store_immutable as store_packet

MODELS = ("glm52", "llama31_70b", "qwen35_35b_a3b")
ATTACK_CONDITIONS = {
    "glm52": "cross_glm52_p001",
    "llama31_70b": "cross_llama31_70b_p001",
    "qwen35_35b_a3b": "cross_qwen35_35b_a3b_p001",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1-config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--cross-config", type=Path, default=Path("configs/stage1_crossed_defense.json")
    )
    parser.add_argument(
        "--cross-manifest",
        type=Path,
        default=Path(
            "artifacts/runs/stage1/development/rag/stage1_crossed_av_1pct_v1/"
            "manifests/crossed_manifest.json"
        ),
    )
    parser.add_argument(
        "--stage2-indexes",
        default=(
            "artifacts/runs/stage2/stage2_signal_v1/private_index.json,"
            "artifacts/runs/stage2/stage2_signal_validation_v1/private_index.json"
        ),
    )
    parser.add_argument("--experiment-id", default="stage2_crossed_defense_v2")
    args = parser.parse_args()

    config = json.loads(args.stage1_config.read_text(encoding="utf-8"))
    cross_config = json.loads(args.cross_config.read_text(encoding="utf-8"))
    cross_manifest = json.loads(args.cross_manifest.read_text(encoding="utf-8"))
    if cross_manifest["failures"] or len(cross_manifest["successes"]) != 549:
        raise ValueError("crossed endpoint manifest is incomplete")
    dataset = json.loads(Path(config["dataset"]["source"]).read_text(encoding="utf-8"))
    split = json.loads(Path("configs/splits/stage234_development.json").read_text(encoding="utf-8"))
    design_ids = set(int(value) for value in split["method_design"]["claim_ids"])
    validation_ids = set(int(value) for value in split["development_validation"]["claim_ids"])
    if len(design_ids) != 60 or len(validation_ids) != 40 or design_ids & validation_ids:
        raise ValueError("unexpected Stage 2 claim partition")

    output_root = Path("artifacts/runs/stage2") / args.experiment_id
    packet_root = output_root / "packets"
    namespace = cross_config["rag_pipeline"]["artifact_namespace"]
    endpoint_root = Path("artifacts/runs/stage1/development/rag") / namespace / "endpoints"
    internal_root = Path("artifacts/runs/stage1/development/internal_endpoint")
    samples, cache_keys = internal_lookup(config, internal_root, Path(config["cache_root"]))
    internal_models = sorted(samples)
    if set(internal_models) != set(MODELS):
        raise ValueError(f"unexpected internal models: {internal_models}")

    ledger = ExperimentLedger(
        Path("artifacts/runs/progress"),
        args.experiment_id,
        description="Attacker-hidden clean and crossed-attack Stage 2 packet construction",
    )
    ledger.update(
        status="running",
        phase="packet_build",
        event="crossed_packet_build_started",
        counts={"expected": 849, "completed": 0},
    )

    rows: list[dict[str, Any]] = []
    clean_seen: set[tuple[str, int]] = set()
    clean_source_rows: list[dict[str, Any]] = []
    for index_path in args.stage2_indexes.split(","):
        index = json.loads(Path(index_path).read_text(encoding="utf-8"))
        for row in index["rows"]:
            if row["condition_id"] != "clean":
                continue
            identity = (row["victim_model_id"], int(row["claim_id"]))
            if identity in clean_seen:
                raise ValueError(f"duplicate clean identity: {identity}")
            clean_seen.add(identity)
            clean_source_rows.append(row)
    if len(clean_source_rows) != 300:
        raise ValueError(f"expected 300 clean rows, found {len(clean_source_rows)}")

    def partition_for(claim_id: int) -> str:
        if claim_id in design_ids:
            return "method_design"
        if claim_id in validation_ids:
            return "development_validation"
        raise ValueError(f"claim outside frozen partitions: {claim_id}")

    def add_endpoint(
        endpoint: dict[str, Any], *, condition_id: str, attacker_model_id: str | None
    ) -> None:
        task = endpoint["task"]
        claim_id = int(task["claim_id"])
        victim_id = str(task.get("model_id", task.get("victim_model_id")))
        if victim_id not in MODELS:
            raise ValueError(f"unexpected victim: {victim_id}")
        if "model_id" not in task:
            # The crossed collection deliberately named this field victim_model_id. The frozen
            # runner consumes the standard RAG task contract with model_id, so create a derived,
            # content-addressed adapter record without modifying the source artifact.
            source_task_key = endpoint["task_key"]
            adapted_task = copy.deepcopy(task)
            adapted_task.pop("task_key", None)
            adapted_task["task_schema_version"] = 4
            adapted_task["task_type"] = "crossed_rag_endpoint_adapter"
            adapted_task["model_id"] = victim_id
            adapted_task["source_cross_task_key"] = source_task_key
            adapted_task["task_key"] = task_key(adapted_task)
            endpoint = normalize_record(
                {
                    "task_key": adapted_task["task_key"],
                    "judgment": endpoint["judgment"],
                    "audit": endpoint["audit"],
                    "provenance": {
                        **endpoint["provenance"],
                        "adapter_contract": "crossed-victim-to-standard-model-id-v1",
                        "source_cross_task_key": source_task_key,
                    },
                },
                adapted_task,
            )
            task = adapted_task
        stored_path, _ = store_endpoint(endpoint_root, endpoint)
        packet = build_packet(
            claim_id=claim_id,
            claim=dataset[claim_id]["claim"],
            claim_date=dataset[claim_id].get("claim_date") or "unknown",
            rag_task_key=endpoint["task_key"],
            rag_judgment=endpoint["judgment"],
            internal_samples={model_id: samples[model_id][claim_id] for model_id in internal_models},
            internal_cache_keys={
                model_id: cache_keys[model_id][claim_id] for model_id in internal_models
            },
        )
        packet_path, _ = store_packet(packet_root, packet)
        rows.append(
            {
                "packet_key": packet["packet_key"],
                "packet_path": str(packet_path),
                "rag_task_key": endpoint["task_key"],
                "rag_artifact_path": str(stored_path),
                "claim_id": claim_id,
                "partition": partition_for(claim_id),
                "victim_model_id": victim_id,
                "condition_id": condition_id,
                "attacker_model_id": attacker_model_id,
            }
        )

    for descriptor in clean_source_rows:
        endpoint_path = (
            Path("artifacts/runs/stage1/development/rag")
            / config["rag_pipeline"]["artifact_namespace"]
            / "endpoints"
            / descriptor["rag_task_key"][:2]
            / f"{descriptor['rag_task_key']}.json"
        )
        add_endpoint(
            json.loads(endpoint_path.read_text(encoding="utf-8")),
            condition_id="clean",
            attacker_model_id=None,
        )

    for descriptor in cross_manifest["successes"]:
        attacker_id = descriptor["attacker_model_id"]
        if attacker_id not in ATTACK_CONDITIONS:
            raise ValueError(f"unexpected attacker: {attacker_id}")
        add_endpoint(
            json.loads(Path(descriptor["artifact_path"]).read_text(encoding="utf-8")),
            condition_id=ATTACK_CONDITIONS[attacker_id],
            attacker_model_id=attacker_id,
        )

    rows.sort(
        key=lambda row: (
            row["claim_id"],
            row["victim_model_id"],
            row["condition_id"],
        )
    )
    identities = {
        (row["claim_id"], row["victim_model_id"], row["condition_id"]) for row in rows
    }
    if len(rows) != 849 or len(identities) != len(rows):
        raise ValueError(f"combined packet identity mismatch: rows={len(rows)} unique={len(identities)}")
    condition_counts = Counter(row["condition_id"] for row in rows)
    victim_counts = Counter(row["victim_model_id"] for row in rows)
    attacker_counts = Counter(
        row["attacker_model_id"] for row in rows if row["attacker_model_id"] is not None
    )
    private_index = {
        "warning": "PRIVATE ROUTING/EVALUATION INDEX: never serialize this object into an LLM prompt",
        "experiment_id": args.experiment_id,
        "partition_request": "all",
        "attack_condition_map": ATTACK_CONDITIONS,
        "rows": rows,
    }
    index_digest = hashlib.sha256(canonical_json(private_index).encode()).hexdigest()
    atomic_json(output_root / "private_index.json", private_index)
    manifest = {
        "manifest_schema_version": 1,
        "experiment_id": args.experiment_id,
        "source_cross_experiment": cross_manifest["experiment_id"],
        "endpoint_namespace": namespace,
        "expected_packet_count": 849,
        "packet_count": len(rows),
        "clean_packet_count": 300,
        "crossed_packet_count": 549,
        "condition_counts": dict(sorted(condition_counts.items())),
        "victim_counts": dict(sorted(victim_counts.items())),
        "attacker_counts": dict(sorted(attacker_counts.items())),
        "private_index_sha256": index_digest,
        "inference_contract": "Only each packet's visible object may be serialized into model messages; attacker identity is private metadata.",
    }
    atomic_json(output_root / "manifest.json", manifest)
    ledger.update(
        status="complete",
        phase="packet_build",
        event="crossed_packet_build_completed",
        counts={"expected": 849, "completed": len(rows)},
        artifacts={"manifest": str(output_root / "manifest.json")},
        details={"private_index_sha256": index_digest},
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
