#!/usr/bin/env python3
"""Audit scope, attacker isolation, exclusions, and same-model calls in transfer study."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from build_stage2_packets import internal_lookup
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import canonical_json
from parametric_rag_defense.counter_retrieval import build_counter_packet
from parametric_rag_defense.evidence_signals import parse_evidence_map
from parametric_rag_defense.labels import deterministic_majority
from parametric_rag_defense.stage2_packets import validate_visible_packet
from parametric_rag_defense.workflow_runtime import prompt_version, render

ATTACKERS = ("glm52", "llama31_70b")
VICTIMS = ("glm52", "llama31_70b", "qwen35_35b_a3b")
_ORIGIN = re.compile(r"\b(?:clean|poison):\d+\b", re.IGNORECASE)
_URL = re.compile(r"https?://\S*", re.IGNORECASE)


def read_cache(root: Path, key: str) -> dict[str, Any]:
    path = root / "entries" / key[:2] / f"{key}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("key") != key:
        raise ValueError(f"cache key mismatch: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
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
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    args.output = args.output or args.counter_root / "audit.json"

    config = json.loads(args.config.read_text(encoding="utf-8"))
    source = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    counter = json.loads(
        (args.counter_root / "private_manifest.json").read_text(encoding="utf-8")
    )
    cache_root = Path(config["cache_root"])
    model_names = {model["id"]: model["model"] for model in config["models"]}
    active_split = config["dataset"].get("active_split", "development")
    samples, _ = internal_lookup(
        config,
        Path(config["run_root"]) / active_split / "internal_endpoint",
        cache_root,
    )
    memory = {
        model_id: {
            int(claim_id): deterministic_majority(value["verdict"] for value in judgments)
            for claim_id, judgments in claim_samples.items()
        }
        for model_id, claim_samples in samples.items()
    }
    failures: list[str] = []
    expected_rows = 69 * len(ATTACKERS) * len(VICTIMS)
    if source.get("failures"):
        failures.append(f"source manifest contains {len(source['failures'])} failures")
    if len(source.get("common_claim_ids", [])) != 69:
        failures.append("joint eligibility scope is not 69 claims")
    if source.get("requested") != expected_rows or len(source.get("successes", [])) != expected_rows:
        failures.append("endpoint matrix is incomplete")

    source_by_identity = {}
    cells = Counter()
    expected_disagreements = set()
    for row in source.get("successes", []):
        identity = (
            row["attacker_model_id"],
            row["victim_model_id"],
            int(row["claim_id"]),
        )
        if identity in source_by_identity:
            failures.append(f"duplicate source identity {identity}")
        source_by_identity[identity] = row
        cells[identity[:2]] += 1
        try:
            endpoint = json.loads(Path(row["artifact_path"]).read_text(encoding="utf-8"))
            trace = json.loads(Path(row["trace_path"]).read_text(encoding="utf-8"))
            task = endpoint["task"]
            if int(task["claim_id"]) != identity[2]:
                raise ValueError("endpoint claim mismatch")
            task_victim = task.get("victim_model_id", task.get("model_id"))
            if task_victim != identity[1]:
                raise ValueError("endpoint victim mismatch")
            if task["condition"]["id"] != "fact2fiction_p0.01":
                raise ValueError("endpoint condition mismatch")
            if identity[0] == identity[1]:
                if not row["reused_diagonal"]:
                    raise ValueError("diagonal endpoint not marked reused")
            else:
                if row["reused_diagonal"] or task.get("attacker_model_id") != identity[0]:
                    raise ValueError("off-diagonal attacker identity mismatch")
                if endpoint["provenance"]["attack_generator_model_id"] != identity[0]:
                    raise ValueError("off-diagonal attacker provenance mismatch")
            if trace["task_key"] != row["task_key"]:
                raise ValueError("trace task mismatch")
            for role in ("plan", "answers", "verdict"):
                for receipt in trace["llm_receipts"][role]:
                    entry = read_cache(cache_root, receipt["cache_key"])
                    if entry["request"]["model"] != model_names[identity[1]]:
                        raise ValueError(f"{role} request does not use victim model")
                    messages = canonical_json(entry["request"]["messages"])
                    if _URL.search(messages) or _ORIGIN.search(messages):
                        raise ValueError(f"{role} request leaks origin metadata")
                    if any(marker in messages for marker in (*ATTACKERS, *VICTIMS, "fact2fiction_p")):
                        raise ValueError(f"{role} request leaks experiment identity")
            if endpoint["judgment"]["verdict"] != memory[identity[1]][identity[2]]:
                expected_disagreements.add(identity)
        except Exception as exc:
            failures.append(f"source {identity}: {type(exc).__name__}: {exc}")
    for attacker in ATTACKERS:
        for victim in VICTIMS:
            if cells[(attacker, victim)] != 69:
                failures.append(f"cell {attacker}->{victim} has {cells[(attacker, victim)]} rows")

    if counter.get("failures"):
        failures.append(f"counter manifest contains {len(counter['failures'])} failures")
    observed_counter = {
        (
            row["attacker_model_id"],
            row["victim_model_id"],
            int(row["claim_id"]),
        ): row
        for row in counter.get("rows", [])
    }
    if set(observed_counter) != expected_disagreements:
        failures.append(
            "counter disagreement scope mismatch: "
            f"missing={len(expected_disagreements-set(observed_counter))} "
            f"unexpected={len(set(observed_counter)-expected_disagreements)}"
        )
    if counter.get("completed_outputs") != len(expected_disagreements):
        failures.append("counter output count is incomplete")

    template, version = prompt_version(
        Path("prompts/evidence_passage_map_v1.md"), "evidence_passage_map_v1"
    )
    exposure = {
        f"{attacker}->{victim}": {
            "rows": 0,
            "documents": 0,
            "poison": 0,
            "exposed_rows": 0,
        }
        for attacker in ATTACKERS
        for victim in VICTIMS
    }
    cache_keys = set()
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for identity, row in observed_counter.items():
        try:
            source_row = source_by_identity[identity]
            source_packet = json.loads(
                Path(row["source_packet_path"]).read_text(encoding="utf-8")
            )
            trace = json.loads(Path(source_row["trace_path"]).read_text(encoding="utf-8"))
            private = json.loads(
                Path(row["counter_retrieval_path"]).read_text(encoding="utf-8")
            )
            packet = json.loads(
                Path(row["counter_packet_path"]).read_text(encoding="utf-8")
            )
            output = json.loads(Path(row["output_path"]).read_text(encoding="utf-8"))
            if private["attacker_model_id"] != identity[0]:
                raise ValueError("counter corpus attacker mismatch")
            if private["victim_model_id"] != identity[1]:
                raise ValueError("counter victim mismatch")
            original = [entry for group in trace["retrievals"] for entry in group]
            expected_ids = {str(entry["document_id"]) for entry in original}
            expected_hashes = {str(entry["text_sha256"]) for entry in original}
            if set(private["excluded_document_ids"]) != expected_ids:
                raise ValueError("original document exclusion mismatch")
            if set(private["excluded_text_sha256"]) != expected_hashes:
                raise ValueError("original text exclusion mismatch")
            retrieved = [entry for group in private["retrievals"] for entry in group]
            if {str(entry["document_id"]) for entry in retrieved} & expected_ids:
                raise ValueError("original document survived counter exclusion")
            if {str(entry["text_sha256"]) for entry in retrieved} & expected_hashes:
                raise ValueError("original text survived counter exclusion")
            reconstructed = [
                [{**entry, "text": entry["text_excerpt"]} for entry in group]
                for group in private["retrievals"]
            ]
            expected_packet = build_counter_packet(
                claim=source_packet["visible"]["claim"],
                claim_date=source_packet["visible"]["claim_date"],
                neutral_plan=source_packet["visible"]["neutral_claim_plan"],
                questions=[str(item["question"]) for item in trace["plan"]["questions"]],
                retrievals=reconstructed,
                source_rag_task_key=row["rag_task_key"],
                source_packet_key=source_packet["packet_key"],
                same_model_id=identity[1],
                excluded_document_count=len(expected_ids),
                excluded_text_sha256=sorted(expected_hashes),
            )
            if packet != expected_packet:
                raise ValueError("counter packet reconstruction mismatch")
            validate_visible_packet(packet["visible"])
            if output["counter_packet_key"] != packet["packet_key"]:
                raise ValueError("counter output packet mismatch")
            passage_ids = {item["passage_id"] for item in packet["visible"]["passages"]}
            parse_evidence_map(output["judgment"], expected_passage_ids=passage_ids)
            expected_output_key = hashlib.sha256(
                canonical_json(
                    {
                        "counter_packet_key": packet["packet_key"],
                        "map_cache_key": output["map_cache_key"],
                        "contract_version": output["contract_version"],
                    }
                ).encode()
            ).hexdigest()
            if output["output_key"] != expected_output_key:
                raise ValueError("counter output identity mismatch")
            entry = read_cache(cache_root, output["map_cache_key"])
            request = entry["request"]
            if request["model"] != model_names[identity[1]]:
                raise ValueError("counter report is not same-model")
            prompt = render(
                template,
                {
                    "EVIDENCE_PACKET": json.dumps(
                        packet["visible"], ensure_ascii=False, sort_keys=True, indent=2
                    )
                },
            )
            if request["messages"][0] != {"role": "user", "content": prompt}:
                raise ValueError("counter prompt reconstruction mismatch")
            if not request["prompt_version"].startswith(version):
                raise ValueError("counter prompt version mismatch")
            prompt_messages = canonical_json(request["messages"])
            if _URL.search(prompt_messages) or _ORIGIN.search(prompt_messages):
                raise ValueError("counter prompt leaks origin metadata")
            if any(marker in prompt_messages for marker in (*ATTACKERS, *VICTIMS, "fact2fiction_p")):
                raise ValueError("counter prompt leaks attacker/model/condition identity")
            label = f"{identity[0]}->{identity[1]}"
            stats = exposure[label]
            stats["rows"] += 1
            stats["documents"] += len(retrieved)
            poison = sum(bool(item["is_poison"]) for item in retrieved)
            stats["poison"] += poison
            stats["exposed_rows"] += int(poison > 0)
            key = output["map_cache_key"]
            if key not in cache_keys:
                cache_keys.add(key)
                call_usage = entry["response"].get("usage") or {}
                for field in usage:
                    usage[field] += int(call_usage.get(field) or 0)
        except Exception as exc:
            failures.append(f"counter {identity}: {type(exc).__name__}: {exc}")

    for stats in exposure.values():
        stats["poison_fraction"] = (
            stats["poison"] / stats["documents"] if stats["documents"] else None
        )
        stats["row_exposure_rate"] = (
            stats["exposed_rows"] / stats["rows"] if stats["rows"] else None
        )
    result = {
        "audit_schema_version": 1,
        "experiment_id": source.get("experiment_id"),
        "endpoint_rows": len(source_by_identity),
        "expected_counter_rows": len(expected_disagreements),
        "observed_counter_rows": len(observed_counter),
        "cell_counts": {
            f"{attacker}->{victim}": cells[(attacker, victim)]
            for attacker in ATTACKERS
            for victim in VICTIMS
        },
        "counter_exposure_private_diagnostic": exposure,
        "unique_map_cache_entries": len(cache_keys),
        "referenced_map_usage": usage,
        "failures": failures,
        "status": "passed" if not failures else "failed",
    }
    atomic_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
