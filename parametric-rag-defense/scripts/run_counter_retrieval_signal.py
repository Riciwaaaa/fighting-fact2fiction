#!/usr/bin/env python3
"""Build leave-original-out counter retrievals and same-model passage reports."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from parametric_rag_defense.averitec import (
    EMBEDDING_CODE_REVISION,
    EMBEDDING_MODEL,
    EMBEDDING_MODEL_REVISION,
    atomic_json,
    read_resources,
)
from parametric_rag_defense.cache import LLMCache, LLMRequest, canonical_json
from parametric_rag_defense.counter_retrieval import (
    COUNTER_PACKET_SCHEMA_VERSION,
    build_counter_packet,
    retrieve_excluding,
)
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.evidence_signals import EVIDENCE_MAP_CONTRACT_VERSION
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.workflow_runtime import (
    prompt_version,
    render,
    store_immutable_output,
)
from run_evidence_signal import execute_evidence_cached


def load_source_rows(run_root: Path) -> list[dict[str, Any]]:
    manifest = json.loads((run_root / "private_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("failures") or manifest.get("completed_outputs") != manifest.get(
        "disagreement_rows"
    ):
        raise ValueError("Source evidence-signal run is incomplete")
    return list(manifest["rows"])


def load_trace(trace_root: Path, task_key: str) -> dict[str, Any]:
    path = trace_root / task_key[:2] / f"{task_key}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("task_key") != task_key:
        raise ValueError(f"Trace task-key mismatch: {path}")
    return value


def counter_identity(source: dict[str, Any]) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "counter_retrieval_schema_version": 1,
                "source_rag_task_key": source["rag_task_key"],
                "source_packet_key": source["packet"]["packet_key"],
                "exclusion_policy": "all-original-documents-and-exact-text-stage1-no-backfill-v2",
                "embedding_model": EMBEDDING_MODEL,
                "embedding_model_revision": EMBEDDING_MODEL_REVISION,
                "embedding_code_revision": EMBEDDING_CODE_REVISION,
                "top_k": 5,
                "evidence_chars": 300,
            }
        ).encode()
    ).hexdigest()


def prepare_sources(
    source_rows: list[dict[str, Any]], trace_root: Path
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    prepared = []
    cases: dict[str, dict[str, Any]] = {}
    for descriptor in source_rows:
        source_packet = json.loads(
            Path(descriptor["packet_path"]).read_text(encoding="utf-8")
        )
        trace = load_trace(trace_root, descriptor["rag_task_key"])
        plan_questions = trace["plan"]["questions"]
        queries = [str(item["query"]).strip() for item in plan_questions]
        questions = [str(item["question"]).strip() for item in plan_questions]
        case = {
            "case_key": descriptor["case_key"],
            "victim_model_id": descriptor["victim_model_id"],
            "claim_id": int(descriptor["claim_id"]),
            "queries": queries,
            "questions": questions,
        }
        existing = cases.setdefault(descriptor["case_key"], case)
        if existing != case:
            raise ValueError(f"Counter query plan changed across conditions: {descriptor['case_key']}")
        prepared.append(
            {
                **descriptor,
                "packet": source_packet,
                "trace": trace,
            }
        )
    return prepared, cases


def embed_cases(cases: dict[str, dict[str, Any]], device: str | None) -> dict[str, Any]:
    from sentence_transformers import SentenceTransformer

    ordered = sorted(cases)
    flattened = [query for key in ordered for query in cases[key]["queries"]]
    embedder = SentenceTransformer(
        EMBEDDING_MODEL,
        revision=EMBEDDING_MODEL_REVISION,
        trust_remote_code=True,
        device=device,
        model_kwargs={"code_revision": EMBEDDING_CODE_REVISION},
    )
    embeddings = embedder.encode(
        flattened,
        batch_size=64,
        show_progress_bar=True,
        convert_to_numpy=True,
    )
    result = {}
    offset = 0
    for key in ordered:
        count = len(cases[key]["queries"])
        result[key] = np.asarray(embeddings[offset : offset + count], dtype="float32")
        offset += count
    return result


def build_counter_artifact(
    *,
    item: dict[str, Any],
    query_embeddings: Any,
    resources_root: Path,
    index_root: Path,
    poison_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    claim_id = int(item["claim_id"])
    model_id = item["victim_model_id"]
    endpoint = json.loads(Path(item["endpoint_path"]).read_text(encoding="utf-8"))
    clean_resources = read_resources(resources_root / f"{claim_id}.json")
    clean_embeddings = np.load(index_root / f"{claim_id}.npy", mmap_mode="r")
    resources: list[dict[str, Any]] = list(clean_resources)
    embedding_parts = [np.asarray(clean_embeddings)]
    injected = int(endpoint["audit"]["poison_documents_injected"])
    if injected:
        poison_path = poison_root / model_id / f"{claim_id}.json"
        poison_record = json.loads(poison_path.read_text(encoding="utf-8"))
        poison_embeddings = np.load(poison_path.with_suffix(".npy"), mmap_mode="r")
        resources.extend(poison_record["documents"][:injected])
        embedding_parts.append(np.asarray(poison_embeddings[:injected]))
    embeddings = np.concatenate(embedding_parts, axis=0)
    original = [entry for group in item["trace"]["retrievals"] for entry in group]
    excluded_document_ids = {str(entry["document_id"]) for entry in original}
    excluded_text_hashes = {str(entry["text_sha256"]) for entry in original}
    retrievals = retrieve_excluding(
        query_embeddings,
        resources,
        embeddings,
        excluded_document_ids=excluded_document_ids,
        excluded_text_sha256=excluded_text_hashes,
        top_k=5,
    )
    identity = counter_identity(item)
    private_record = {
        "counter_retrieval_schema_version": 1,
        "counter_retrieval_key": identity,
        "source_rag_task_key": item["rag_task_key"],
        "source_packet_key": item["packet"]["packet_key"],
        "victim_model_id": model_id,
        "claim_id": claim_id,
        "condition_id": item["condition_id"],
        "exclusion_policy": "all-original-documents-and-exact-text-stage1-no-backfill-v2",
        "excluded_document_ids": sorted(excluded_document_ids),
        "excluded_text_sha256": sorted(excluded_text_hashes),
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
    source_visible = item["packet"]["visible"]
    packet = build_counter_packet(
        claim=source_visible["claim"],
        claim_date=source_visible["claim_date"],
        neutral_plan=source_visible["neutral_claim_plan"],
        questions=item["trace"]["plan"] and [
            str(value["question"]) for value in item["trace"]["plan"]["questions"]
        ],
        retrievals=retrievals,
        source_rag_task_key=item["rag_task_key"],
        source_packet_key=item["packet"]["packet_key"],
        same_model_id=model_id,
        excluded_document_count=len(excluded_document_ids),
        excluded_text_sha256=sorted(excluded_text_hashes),
        evidence_chars=300,
    )
    return private_record, packet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--source-run-root",
        type=Path,
        default=Path("artifacts/runs/evidence_signal/evidence_signal_v1"),
    )
    parser.add_argument("--experiment-id", default="counter_retrieval_signal_v2")
    parser.add_argument("--phase", choices=("prepare", "retrieve", "map", "all"), default="all")
    parser.add_argument("--device")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--contract-retries", type=int, default=2)
    args = parser.parse_args()
    if args.workers < 1 or args.contract_retries < 0:
        raise SystemExit("workers must be positive and contract retries nonnegative")

    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    active_split = config["dataset"].get("active_split", "development")
    namespace_root = (
        Path(config["run_root"])
        / active_split
        / "rag"
        / config["rag_pipeline"]["artifact_namespace"]
    )
    trace_root = namespace_root / "private_traces"
    source_rows = load_source_rows(args.source_run_root)
    prepared, cases = prepare_sources(source_rows, trace_root)
    condition_counts = dict(sorted(Counter(row["condition_id"] for row in prepared).items()))
    preflight = {
        "experiment_id": args.experiment_id,
        "rows": len(prepared),
        "unique_model_claim_cases": len(cases),
        "condition_counts": condition_counts,
        "maximum_map_calls": len(prepared),
        "query_generation_calls": 0,
    }
    if args.phase == "prepare":
        print(json.dumps(preflight, indent=2, sort_keys=True))
        return

    study_parent = Path(config["run_root"]).parent
    run_root = study_parent / "counter_retrieval" / args.experiment_id
    retrieval_root = run_root / "private_retrievals"
    packet_root = run_root / "packets"
    output_root = run_root / "outputs"
    ledger = ExperimentLedger(
        Path(config.get("progress_root", "artifacts/runs/progress")),
        args.experiment_id,
        description="Leave-original-out counter retrieval and same-model passage reports",
    )
    failures: list[dict[str, Any]] = []
    manifest_rows = []
    prior_rows_by_retrieval_key: dict[str, dict[str, Any]] = {}
    prior_manifest_path = run_root / "private_manifest.json"
    if prior_manifest_path.exists():
        prior_manifest = json.loads(prior_manifest_path.read_text(encoding="utf-8"))
        prior_rows_by_retrieval_key = {
            str(row["counter_retrieval_key"]): row
            for row in prior_manifest.get("rows", [])
            if row.get("counter_retrieval_key")
        }

    need_retrieval = args.phase in {"retrieve", "all"}
    embeddings_by_case = embed_cases(cases, args.device) if need_retrieval else {}
    for completed, item in enumerate(prepared, 1):
        identity = counter_identity(item)
        retrieval_path = retrieval_root / identity[:2] / f"{identity}.json"
        packet: dict[str, Any]
        try:
            if retrieval_path.exists():
                private_record = json.loads(retrieval_path.read_text(encoding="utf-8"))
                if private_record.get("counter_retrieval_key") != identity:
                    raise ValueError(f"Counter retrieval identity mismatch: {retrieval_path}")
                prior_row = prior_rows_by_retrieval_key.get(identity, {})
                prior_packet_path = Path(str(prior_row.get("counter_packet_path", "")))
                if prior_packet_path.is_file():
                    packet = json.loads(prior_packet_path.read_text(encoding="utf-8"))
                else:
                    # Reconstruct retrieval entries for packet creation from the retained excerpts.
                    reconstructed = [
                        [
                            {**entry, "text": entry["text_excerpt"]}
                            for entry in group
                        ]
                        for group in private_record["retrievals"]
                    ]
                    source_visible = item["packet"]["visible"]
                    packet = build_counter_packet(
                        claim=source_visible["claim"],
                        claim_date=source_visible["claim_date"],
                        neutral_plan=source_visible["neutral_claim_plan"],
                        questions=[
                            str(value["question"])
                            for value in item["trace"]["plan"]["questions"]
                        ],
                        retrievals=reconstructed,
                        source_rag_task_key=item["rag_task_key"],
                        source_packet_key=item["packet"]["packet_key"],
                        same_model_id=item["victim_model_id"],
                        excluded_document_count=len(
                            private_record["excluded_document_ids"]
                        ),
                        excluded_text_sha256=private_record["excluded_text_sha256"],
                    )
            elif need_retrieval:
                private_record, packet = build_counter_artifact(
                    item=item,
                    query_embeddings=embeddings_by_case[item["case_key"]],
                    resources_root=Path(
                        config.get("data_root", "artifacts/data/averitec")
                    ) / "resources",
                    index_root=Path(
                        config.get("data_root", "artifacts/data/averitec")
                    ) / "indexes" / "gte-base-en-v1.5",
                    poison_root=namespace_root / "poison_corpora",
                )
                store_immutable_output(retrieval_root, identity, private_record)
            else:
                raise ValueError(f"Missing counter retrieval for map phase: {identity}")
            packet_path, _ = store_immutable_output(packet_root, packet["packet_key"], packet)
            manifest_rows.append(
                {
                    **{
                        key: value
                        for key, value in item.items()
                        if key not in {"packet", "trace"}
                    },
                    "counter_retrieval_key": identity,
                    "counter_retrieval_path": str(retrieval_path),
                    "counter_packet_key": packet["packet_key"],
                    "counter_packet_path": str(packet_path),
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "phase": "retrieve",
                    "identity": identity,
                    "error": repr(exc),
                    "traceback": traceback.format_exc(),
                }
            )
        if completed % 20 == 0 or completed == len(prepared):
            print(f"counter_retrieve {completed}/{len(prepared)} failures={len(failures)}")
    manifest_rows.sort(
        key=lambda row: (row["claim_id"], row["victim_model_id"], row["condition_id"])
    )
    retrieval_manifest = {
        "manifest_schema_version": 1,
        **preflight,
        "counter_packet_schema_version": COUNTER_PACKET_SCHEMA_VERSION,
        "retrieval_rows": len(manifest_rows),
        "rows": manifest_rows,
        "failures": failures,
    }
    atomic_json(run_root / "private_manifest.json", retrieval_manifest)
    ledger.update(
        status="complete" if not failures and len(manifest_rows) == len(prepared) else "failed",
        phase="counter_retrieval",
        event="counter_retrieval_completed",
        counts={"expected": len(prepared), "completed": len(manifest_rows), "failed": len(failures)},
        artifacts={"manifest": str(run_root / "private_manifest.json")},
    )
    if failures or len(manifest_rows) != len(prepared):
        raise SystemExit(1)
    if args.phase == "retrieve":
        return

    load_dotenv(config_path.parent.parent / ".env")
    models = {
        model["id"]: model
        for model in config["models"]
        if model.get("enabled") and "arbiter" in model["roles"]
    }
    template, version = prompt_version(
        Path("prompts/evidence_passage_map_v1.md"), "evidence_passage_map_v1"
    )
    cache = LLMCache(Path(config["cache_root"]).resolve())

    def map_one(row: dict[str, Any]) -> dict[str, Any]:
        packet = json.loads(Path(row["counter_packet_path"]).read_text(encoding="utf-8"))
        prompt = render(
            template,
            {
                "EVIDENCE_PACKET": json.dumps(
                    packet["visible"], ensure_ascii=False, sort_keys=True, indent=2
                )
            },
        )
        model = models[row["victim_model_id"]]
        request = LLMRequest(
            stage="counter_retrieval_passage_map_v1",
            provider=model["provider"],
            model=model["model"],
            prompt_id="counter_retrieval_passage_map",
            prompt_version=version,
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
                "role": "counter_retrieval_passage_map",
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
        output_path, cached = store_immutable_output(output_root, output_key, output)
        return {
            "output_key": output_key,
            "output_path": str(output_path),
            "map_cache_key": receipts[-1]["cache_key"],
            "cache_hit": receipts[-1]["cache_hit"],
            "cached_output": cached,
            "receipts": receipts,
        }

    map_results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(map_one, row): row["counter_retrieval_key"]
            for row in manifest_rows
        }
        for completed, future in enumerate(concurrent.futures.as_completed(futures), 1):
            identity = futures[future]
            try:
                map_results[identity] = future.result()
            except Exception as exc:
                failures.append(
                    {
                        "phase": "map",
                        "identity": identity,
                        "error": repr(exc),
                        "traceback": traceback.format_exc(),
                        "receipts": getattr(exc, "receipts", None),
                    }
                )
            if completed % 10 == 0 or completed == len(futures):
                print(f"counter_map {completed}/{len(futures)} failures={len(failures)}")
    final_rows = []
    for row in manifest_rows:
        result = map_results.get(row["counter_retrieval_key"])
        if result:
            final_rows.append({**row, **result})
    final_manifest = {
        **retrieval_manifest,
        "completed_outputs": len(final_rows),
        "evidence_map_contract_version": EVIDENCE_MAP_CONTRACT_VERSION,
        "rows": final_rows,
        "failures": failures,
    }
    atomic_json(run_root / "private_manifest.json", final_manifest)
    status = "complete" if not failures and len(final_rows) == len(prepared) else "failed"
    ledger.update(
        status=status,
        phase="counter_map",
        event="counter_map_completed" if status == "complete" else "counter_map_failed",
        counts={"expected": len(prepared), "completed": len(final_rows), "failed": len(failures)},
        artifacts={"manifest": str(run_root / "private_manifest.json")},
    )
    print(json.dumps({"status": status, "outputs": len(final_rows), "failures": len(failures)}, indent=2))
    if status != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
