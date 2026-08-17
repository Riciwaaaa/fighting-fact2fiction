#!/usr/bin/env python3
"""Collect same-corpus counter-view reports for attacker-transfer disagreements."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from build_stage2_packets import internal_lookup
from parametric_rag_defense.averitec import (
    EMBEDDING_CODE_REVISION,
    EMBEDDING_MODEL,
    EMBEDDING_MODEL_REVISION,
    atomic_json,
    read_resources,
)
from parametric_rag_defense.cache import LLMCache, LLMRequest, canonical_json
from parametric_rag_defense.counter_retrieval import build_counter_packet, retrieve_excluding
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.evidence_signals import (
    EVIDENCE_MAP_CONTRACT_VERSION,
    build_evidence_packet,
)
from parametric_rag_defense.labels import deterministic_majority
from parametric_rag_defense.neutral_firewall import parse_neutral_plan_text
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.workflow_runtime import (
    execute_cached,
    prompt_version,
    render,
    store_immutable_output,
)
from run_counter_retrieval_signal import counter_identity, embed_cases
from run_evidence_signal import case_key, execute_evidence_cached


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
        "--experiment-id", default="environment_confirmation_transfer_counter_v1"
    )
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--contract-retries", type=int, default=10)
    args = parser.parse_args()
    if args.workers < 1 or args.contract_retries < 0:
        raise SystemExit("workers must be positive and contract retries nonnegative")

    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    load_dotenv(config_path.parent.parent / ".env")
    source = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    if source.get("failures") or len(source.get("successes", [])) != source.get("requested"):
        raise ValueError("attacker-transfer endpoint manifest is incomplete")
    dataset = json.loads(Path(config["dataset"]["source"]).read_text(encoding="utf-8"))
    active_split = config["dataset"].get("active_split", "development")
    models = {
        model["id"]: model
        for model in config["models"]
        if model.get("enabled") and "arbiter" in model["roles"]
    }
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

    rows: list[dict[str, Any]] = []
    cases: dict[str, dict[str, Any]] = {}
    for descriptor in source["successes"]:
        endpoint = json.loads(Path(descriptor["artifact_path"]).read_text(encoding="utf-8"))
        victim_id = descriptor["victim_model_id"]
        claim_id = int(descriptor["claim_id"])
        memory_prediction = memory[victim_id][claim_id]
        rag_prediction = endpoint["judgment"]["verdict"]
        if rag_prediction == memory_prediction:
            continue
        record = dataset[claim_id]
        claim = str(record["claim"]).strip()
        claim_date = str(record.get("claim_date") or "unknown")
        current_case_key = case_key(victim_id, claim, claim_date)
        trace = json.loads(Path(descriptor["trace_path"]).read_text(encoding="utf-8"))
        case = {
            "case_key": current_case_key,
            "model_id": victim_id,
            "claim": claim,
            "claim_date": claim_date,
            "queries": [str(item["query"]).strip() for item in trace["plan"]["questions"]],
            "questions": [
                str(item["question"]).strip() for item in trace["plan"]["questions"]
            ],
        }
        existing = cases.setdefault(current_case_key, case)
        if existing != case:
            raise ValueError(f"victim query plan changed across attackers: {current_case_key}")
        rows.append(
            {
                **descriptor,
                "rag_task_key": descriptor["task_key"],
                "endpoint_path": descriptor["artifact_path"],
                "case_key": current_case_key,
                "rag_prediction": rag_prediction,
                "memory_prediction": memory_prediction,
            }
        )
    rows.sort(
        key=lambda row: (
            row["attacker_model_id"],
            row["victim_model_id"],
            row["claim_id"],
        )
    )

    run_root = (
        Path(config["run_root"]).parent
        / "attacker_transfer_counter"
        / args.experiment_id
    )
    source_packet_root = run_root / "source_packets"
    retrieval_root = run_root / "private_retrievals"
    counter_packet_root = run_root / "counter_packets"
    output_root = run_root / "outputs"
    cache = LLMCache(Path(config["cache_root"]).resolve())
    ledger = ExperimentLedger(
        Path(config.get("progress_root", Path(config["run_root"]).parent / "progress")),
        args.experiment_id,
        description="Counter-view evidence for the frozen attacker-transfer secondary",
    )
    failures: list[dict[str, Any]] = []
    ledger.update(
        status="running",
        phase="preparation",
        event="transfer_counter_started",
        counts={
            "endpoint_rows": len(source["successes"]),
            "disagreements": len(rows),
            "unique_cases": len(cases),
            "failed": 0,
        },
    )

    plan_template, plan_version = prompt_version(
        Path("prompts/neutral_claim_plan_v1.md"), "neutral_claim_plan_v1"
    )

    def plan_one(case: dict[str, Any]) -> dict[str, Any]:
        model = models[case["model_id"]]
        prompt = render(
            plan_template,
            {"CLAIM": case["claim"], "CLAIM_DATE": case["claim_date"]},
        )
        request = LLMRequest(
            stage="stage5_neutral_claim_plan",
            provider=model["provider"],
            model=model["model"],
            prompt_id="neutral_claim_plan",
            prompt_version=plan_version,
            messages=[{"role": "user", "content": prompt}],
            parameters={
                "temperature": 0.2,
                "top_p": 0.7,
                "max_tokens": 1000,
                "seed": 97,
                **model.get("request_parameters", {}),
            },
            response_format={"type": "json_object"},
        )
        judgment, receipts = execute_cached(
            cache=cache,
            request=request,
            parser=parse_neutral_plan_text,
            metadata={
                "role": "transfer_counter_claim_plan",
                "case_key": case["case_key"],
                "model_id": case["model_id"],
            },
            contract_name="neutral claim-plan contract",
            retries=args.contract_retries,
        )
        return {
            "judgment": judgment,
            "cache_key": receipts[-1]["cache_key"],
            "receipts": receipts,
        }

    plans: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(plan_one, case): current_case_key
            for current_case_key, case in cases.items()
        }
        for completed, future in enumerate(concurrent.futures.as_completed(futures), 1):
            current_case_key = futures[future]
            try:
                plans[current_case_key] = future.result()
            except Exception as exc:
                failures.append(
                    {
                        "phase": "claim_plan",
                        "identity": current_case_key,
                        "error": repr(exc),
                        "traceback": traceback.format_exc(),
                    }
                )
            if completed % 20 == 0 or completed == len(futures):
                print(f"transfer_plan {completed}/{len(futures)} failures={len(failures)}")
    if failures or len(plans) != len(cases):
        raise SystemExit("transfer claim-plan collection incomplete")

    prepared: list[dict[str, Any]] = []
    for row in rows:
        endpoint = json.loads(Path(row["endpoint_path"]).read_text(encoding="utf-8"))
        case = cases[row["case_key"]]
        plan = plans[row["case_key"]]
        source_packet = build_evidence_packet(
            claim=case["claim"],
            claim_date=case["claim_date"],
            rag_task_key=row["rag_task_key"],
            rag_judgment=endpoint["judgment"],
            neutral_plan=plan["judgment"],
            neutral_plan_cache_key=plan["cache_key"],
            same_model_id=row["victim_model_id"],
        )
        source_packet_path, _ = store_immutable_output(
            source_packet_root, source_packet["packet_key"], source_packet
        )
        prepared.append(
            {
                **row,
                "packet": source_packet,
                "source_packet_path": str(source_packet_path),
                "plan_cache_key": plan["cache_key"],
            }
        )

    query_embeddings = embed_cases(cases, args.device)
    stage1_namespace = (
        Path(config["run_root"])
        / active_split
        / "rag"
        / config["rag_pipeline"]["artifact_namespace"]
    )
    retrieval_rows: list[dict[str, Any]] = []
    for completed, item in enumerate(prepared, 1):
        identity = counter_identity(item)
        retrieval_path = retrieval_root / identity[:2] / f"{identity}.json"
        try:
            trace = json.loads(Path(item["trace_path"]).read_text(encoding="utf-8"))
            if retrieval_path.exists():
                private = json.loads(retrieval_path.read_text(encoding="utf-8"))
                if private.get("counter_retrieval_key") != identity:
                    raise ValueError("counter retrieval identity mismatch")
                retrievals = [
                    [{**entry, "text": entry["text_excerpt"]} for entry in group]
                    for group in private["retrievals"]
                ]
            else:
                claim_id = int(item["claim_id"])
                clean_resources = read_resources(
                    Path(config["data_root"]) / "resources" / f"{claim_id}.json"
                )
                clean_embeddings = np.load(
                    Path(config["data_root"])
                    / "indexes"
                    / "gte-base-en-v1.5"
                    / f"{claim_id}.npy",
                    mmap_mode="r",
                )
                endpoint = json.loads(
                    Path(item["endpoint_path"]).read_text(encoding="utf-8")
                )
                injected = int(endpoint["audit"]["poison_documents_injected"])
                material_path = (
                    stage1_namespace
                    / "poison_corpora"
                    / item["attacker_model_id"]
                    / f"{claim_id}.json"
                )
                material = json.loads(material_path.read_text(encoding="utf-8"))
                poison_embeddings = np.load(material_path.with_suffix(".npy"), mmap_mode="r")
                resources = [*clean_resources, *material["documents"][:injected]]
                embeddings = np.concatenate(
                    [
                        np.asarray(clean_embeddings),
                        np.asarray(poison_embeddings[:injected]),
                    ],
                    axis=0,
                )
                original = [entry for group in trace["retrievals"] for entry in group]
                excluded_ids = {str(entry["document_id"]) for entry in original}
                excluded_hashes = {str(entry["text_sha256"]) for entry in original}
                retrievals = retrieve_excluding(
                    query_embeddings[item["case_key"]],
                    resources,
                    embeddings,
                    excluded_document_ids=excluded_ids,
                    excluded_text_sha256=excluded_hashes,
                    top_k=5,
                )
                private = {
                    "counter_retrieval_schema_version": 1,
                    "counter_retrieval_key": identity,
                    "source_rag_task_key": item["rag_task_key"],
                    "source_packet_key": item["packet"]["packet_key"],
                    "attacker_model_id": item["attacker_model_id"],
                    "victim_model_id": item["victim_model_id"],
                    "claim_id": claim_id,
                    "condition_id": item["condition_id"],
                    "exclusion_policy": "all-original-documents-and-exact-text-stage1-no-backfill-v2",
                    "excluded_document_ids": sorted(excluded_ids),
                    "excluded_text_sha256": sorted(excluded_hashes),
                    "poison_documents_injected": injected,
                    "retrievals": [
                        [
                            {
                                "document_id": entry["document_id"],
                                "is_poison": bool(entry["is_poison"]),
                                "rank": entry["rank"],
                                "distance": entry["distance"],
                                "text_sha256": entry["text_sha256"],
                                "text_excerpt": str(entry["text"])[:300],
                            }
                            for entry in group
                        ]
                        for group in retrievals
                    ],
                }
                store_immutable_output(retrieval_root, identity, private)
            original = [entry for group in trace["retrievals"] for entry in group]
            counter_packet = build_counter_packet(
                claim=item["packet"]["visible"]["claim"],
                claim_date=item["packet"]["visible"]["claim_date"],
                neutral_plan=item["packet"]["visible"]["neutral_claim_plan"],
                questions=cases[item["case_key"]]["questions"],
                retrievals=retrievals,
                source_rag_task_key=item["rag_task_key"],
                source_packet_key=item["packet"]["packet_key"],
                same_model_id=item["victim_model_id"],
                excluded_document_count=len(
                    {str(entry["document_id"]) for entry in original}
                ),
                excluded_text_sha256=sorted(
                    {str(entry["text_sha256"]) for entry in original}
                ),
            )
            counter_packet_path, _ = store_immutable_output(
                counter_packet_root, counter_packet["packet_key"], counter_packet
            )
            retrieval_rows.append(
                {
                    **{key: value for key, value in item.items() if key != "packet"},
                    "counter_retrieval_key": identity,
                    "counter_retrieval_path": str(retrieval_path),
                    "counter_packet_key": counter_packet["packet_key"],
                    "counter_packet_path": str(counter_packet_path),
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "phase": "counter_retrieval",
                    "identity": identity,
                    "error": repr(exc),
                    "traceback": traceback.format_exc(),
                }
            )
        if completed % 20 == 0 or completed == len(prepared):
            print(f"transfer_retrieve {completed}/{len(prepared)} failures={len(failures)}")
    if failures or len(retrieval_rows) != len(prepared):
        raise SystemExit("transfer counter retrieval incomplete")

    evidence_template, evidence_version = prompt_version(
        Path("prompts/evidence_passage_map_v1.md"), "evidence_passage_map_v1"
    )

    def map_one(row: dict[str, Any]) -> dict[str, Any]:
        packet = json.loads(Path(row["counter_packet_path"]).read_text(encoding="utf-8"))
        model = models[row["victim_model_id"]]
        prompt = render(
            evidence_template,
            {
                "EVIDENCE_PACKET": json.dumps(
                    packet["visible"], ensure_ascii=False, sort_keys=True, indent=2
                )
            },
        )
        request = LLMRequest(
            stage="counter_retrieval_passage_map_v1",
            provider=model["provider"],
            model=model["model"],
            prompt_id="counter_retrieval_passage_map",
            prompt_version=evidence_version,
            messages=[{"role": "user", "content": prompt}],
            parameters={
                "temperature": 0.1,
                "top_p": 0.7,
                "max_tokens": 6000,
                "seed": 431,
                **model.get("request_parameters", {}),
            },
            response_format={"type": "json_object"},
        )
        expected_ids = {
            passage["passage_id"] for passage in packet["visible"]["passages"]
        }
        judgment, receipts = execute_evidence_cached(
            cache=cache,
            request=request,
            expected_passage_ids=expected_ids,
            metadata={
                "role": "transfer_counter_passage_map",
                "packet_key": packet["packet_key"],
                "model_id": row["victim_model_id"],
            },
            retries=args.contract_retries,
        )
        output_key = hashlib.sha256(
            canonical_json(
                {
                    "counter_packet_key": packet["packet_key"],
                    "map_cache_key": receipts[-1]["cache_key"],
                    "contract_version": EVIDENCE_MAP_CONTRACT_VERSION,
                }
            ).encode()
        ).hexdigest()
        output = {
            "output_schema_version": 1,
            "contract_version": EVIDENCE_MAP_CONTRACT_VERSION,
            "output_key": output_key,
            "counter_packet_key": packet["packet_key"],
            "map_cache_key": receipts[-1]["cache_key"],
            "judgment": judgment,
        }
        output_path, cached_output = store_immutable_output(
            output_root, output_key, output
        )
        return {
            "output_key": output_key,
            "output_path": str(output_path),
            "map_cache_key": receipts[-1]["cache_key"],
            "cache_hit": receipts[-1]["cache_hit"],
            "cached_output": cached_output,
            "receipts": receipts,
        }

    map_results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(map_one, row): row["counter_retrieval_key"]
            for row in retrieval_rows
        }
        for completed, future in enumerate(concurrent.futures.as_completed(futures), 1):
            identity = futures[future]
            try:
                map_results[identity] = future.result()
            except Exception as exc:
                failures.append(
                    {
                        "phase": "counter_map",
                        "identity": identity,
                        "error": repr(exc),
                        "traceback": traceback.format_exc(),
                        "receipts": getattr(exc, "receipts", None),
                    }
                )
            if completed % 10 == 0 or completed == len(futures):
                print(f"transfer_map {completed}/{len(futures)} failures={len(failures)}")

    final_rows = [
        {**row, **map_results[row["counter_retrieval_key"]]}
        for row in retrieval_rows
        if row["counter_retrieval_key"] in map_results
    ]
    manifest = {
        "manifest_schema_version": 1,
        "experiment_id": args.experiment_id,
        "source_manifest": str(args.source_manifest),
        "endpoint_rows": len(source["successes"]),
        "disagreement_rows": len(rows),
        "unique_model_claim_cases": len(cases),
        "completed_plans": len(plans),
        "completed_retrievals": len(retrieval_rows),
        "completed_outputs": len(final_rows),
        "rows": final_rows,
        "failures": failures,
    }
    atomic_json(run_root / "private_manifest.json", manifest)
    status = "complete" if not failures and len(final_rows) == len(rows) else "failed"
    ledger.update(
        status=status,
        phase="counter_map",
        event=f"transfer_counter_{status}",
        counts={
            "expected": len(rows),
            "completed": len(final_rows),
            "failed": len(failures),
        },
        artifacts={"manifest": str(run_root / "private_manifest.json")},
    )
    print(
        json.dumps(
            {
                "status": status,
                "endpoint_rows": len(source["successes"]),
                "disagreements": len(rows),
                "outputs": len(final_rows),
                "failures": len(failures),
            },
            indent=2,
        )
    )
    if status != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
