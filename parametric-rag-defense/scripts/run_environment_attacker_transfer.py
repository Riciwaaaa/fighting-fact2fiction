#!/usr/bin/env python3
"""Run the prespecified 1% two-attacker transfer matrix on confirmation claims."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import traceback
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import (
    EMBEDDING_CODE_REVISION,
    EMBEDDING_MODEL,
    EMBEDDING_MODEL_REVISION,
    atomic_json,
    poison_document_count,
    read_resources,
    realized_poison_fraction,
)
from parametric_rag_defense.matrix import task_key
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.rag_artifacts import artifact_path, normalize_record, store_immutable
from run_stage1_rag_scan import (
    STRUCTURED_CONTRACT_VERSION,
    UPSTREAM_PIPELINE,
    UPSTREAM_SOURCE,
    VICTIM_EVIDENCE_CONTRACT,
    ScanRunner,
    mask_urls,
    neutral_evidence_id,
)

RATE = 0.01
CONDITION = "fact2fiction_p0.01"
ATTACKERS = ("glm52", "llama31_70b")
VICTIMS = ("glm52", "llama31_70b", "qwen35_35b_a3b")


def transfer_task(base_task: dict[str, Any], attacker_id: str) -> dict[str, Any]:
    task = {
        key: value
        for key, value in base_task.items()
        if key not in {"task_key", "task_schema_version", "task_type", "tier"}
    }
    task.update(
        {
            "task_schema_version": 5,
            "task_type": "environment_confirmation_attacker_transfer_endpoint",
            "diagnostic_id": "environment_confirmation_attacker_transfer_v1",
            "attacker_model_id": attacker_id,
            "victim_model_id": base_task["model_id"],
        }
    )
    task["task_key"] = task_key(task)
    return task


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/stage1_environment_confirmation_train_v1.json"),
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--contract-retries", type=int, default=5)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--evidence-chars", type=int, default=1800)
    parser.add_argument(
        "--experiment-id", default="environment_confirmation_attacker_transfer_v1"
    )
    parser.add_argument(
        "--namespace", default="environment_confirmation_attacker_transfer_v1"
    )
    args = parser.parse_args()
    if args.workers < 1 or args.contract_retries < 0 or args.evidence_chars < 200:
        raise SystemExit("invalid workers, retries, or evidence character limit")

    runner_args = argparse.Namespace(
        config=args.config,
        dataset=None,
        data_root=None,
        phase="poison",
        tier="fresh_confirmation_curve",
        artifact_label=None,
        models=",".join(VICTIMS),
        claims=None,
        workers=args.workers,
        contract_retries=args.contract_retries,
        device=args.device,
        evidence_chars=args.evidence_chars,
        experiment_id=args.experiment_id,
    )
    runner = ScanRunner(runner_args)
    runner.load_embedder()
    by_id = {model["id"]: model for model in runner.models}
    if set(by_id) != set(VICTIMS):
        raise SystemExit(f"expected victims {VICTIMS}, found {sorted(by_id)}")

    eligibility = json.loads(runner.eligibility_path.read_text(encoding="utf-8"))
    common_claims = sorted(
        set.intersection(
            *(
                set(eligibility["models"][model_id]["eligible_claim_ids"])
                for model_id in VICTIMS
            )
        )
    )
    if len(common_claims) != 69:
        raise SystemExit(
            f"frozen joint clean-correct scope changed: expected 69, found {len(common_claims)}"
        )

    source_root = runner.run_root
    output_root = runner.study_root / "rag" / args.namespace
    endpoint_root = output_root / "endpoints"
    trace_root = output_root / "private_traces"
    manifest_path = output_root / "manifests" / "transfer_manifest.json"
    ledger = ExperimentLedger(
        Path(runner.config.get("progress_root", Path(runner.config["run_root"]).parent / "progress")),
        args.experiment_id,
        description="Prespecified 1% two-attacker transfer on joint confirmation eligibility",
    )
    jobs = [
        (attacker_id, victim_id, claim_id)
        for attacker_id in ATTACKERS
        for victim_id in VICTIMS
        for claim_id in common_claims
    ]
    ledger.update(
        status="running",
        phase="crossed_endpoints",
        event="attacker_transfer_started",
        counts={"expected": len(jobs), "completed": 0, "failed": 0, "cached": 0},
        details={"joint_claims": len(common_claims)},
        artifacts={"manifest": str(manifest_path)},
    )

    def execute(attacker_id: str, victim_id: str, claim_id: int) -> dict[str, Any]:
        import numpy as np

        victim = by_id[victim_id]
        base_task = runner.task_for(victim_id, claim_id, CONDITION)
        if attacker_id == victim_id:
            endpoint_path = artifact_path(source_root / "endpoints", base_task["task_key"])
            trace_path = artifact_path(source_root / "private_traces", base_task["task_key"])
            if not endpoint_path.exists() or not trace_path.exists():
                raise FileNotFoundError(endpoint_path)
            return {
                "task_key": base_task["task_key"],
                "artifact_path": str(endpoint_path),
                "trace_path": str(trace_path),
                "cached_artifact": True,
                "reused_diagonal": True,
            }

        task = transfer_task(base_task, attacker_id)
        endpoint_path = artifact_path(endpoint_root, task["task_key"])
        trace_path = artifact_path(trace_root, task["task_key"])
        if endpoint_path.exists() and trace_path.exists():
            return {
                "task_key": task["task_key"],
                "artifact_path": str(endpoint_path),
                "trace_path": str(trace_path),
                "cached_artifact": True,
                "reused_diagonal": False,
            }

        material_path = source_root / "poison_corpora" / attacker_id / f"{claim_id}.json"
        material = json.loads(material_path.read_text(encoding="utf-8"))
        all_embeddings = np.load(material_path.with_suffix(".npy"), mmap_mode="r")
        if len(material["documents"]) != all_embeddings.shape[0]:
            raise RuntimeError(f"poison material/embedding mismatch: {attacker_id}/{claim_id}")
        clean_count = len(read_resources(runner.resources_root / f"{claim_id}.json"))
        injected = poison_document_count(clean_count, RATE)
        poison_documents = material["documents"][:injected]
        poison_embeddings = all_embeddings[:injected]

        plan, plan_receipts = runner.plan(victim, claim_id)
        retrievals, retrieved_total, retrieved_poison = runner.retrieval(
            claim_id, plan, poison_documents, poison_embeddings
        )
        answers, answer_receipts = runner.answer_questions(
            victim, claim_id, plan, retrievals, CONDITION
        )
        verdict, verdict_receipts = runner.final_verdict(
            victim, claim_id, plan, answers, retrievals, CONDITION
        )
        questions = []
        for question_index, (planned, answer, results) in enumerate(
            zip(plan["questions"], answers["answers"], retrievals)
        ):
            questions.append(
                {
                    "question": mask_urls(planned["question"]),
                    "status": answer["status"],
                    "answer": mask_urls(answer["answer"]),
                    "selected_rank": answer["selected_rank"],
                    "evidence": [
                        f"[{neutral_evidence_id(question_index, rank)}] "
                        f"{mask_urls(result['text'][:300])}"
                        for rank, result in enumerate(results, 1)
                    ],
                }
            )
        record = {
            "task_key": task["task_key"],
            "judgment": {
                "verdict": verdict["verdict"],
                "confidence": verdict["confidence"],
                "justification": mask_urls(verdict["justification"]),
                "questions": questions,
            },
            "audit": {
                "clean_documents_before_injection": clean_count,
                "poison_documents_injected": injected,
                "realized_poison_fraction": realized_poison_fraction(clean_count, injected),
                "retrieved_documents_total": retrieved_total,
                "retrieved_poison_documents": retrieved_poison,
            },
            "provenance": {
                "pipeline": runner.config["rag_pipeline"]["id"],
                "pipeline_version": runner.config["rag_pipeline"]["version"],
                "diagnostic_id": "environment_confirmation_attacker_transfer_v1",
                "attack_generator_model_id": attacker_id,
                "victim_model_id": victim_id,
                "source_poison_documents_sha256": material["documents_sha256"],
                "source_poison_prefix_count": injected,
                "structured_contract_version": STRUCTURED_CONTRACT_VERSION,
                "victim_evidence_contract": VICTIM_EVIDENCE_CONTRACT,
                "source_identifiers": "origin-free per-question evidence IDs",
                "urls_masked_before_victim": True,
                "upstream_pipeline": UPSTREAM_PIPELINE,
                "upstream_source": UPSTREAM_SOURCE,
                "embedding_model": EMBEDDING_MODEL,
                "embedding_model_revision": EMBEDDING_MODEL_REVISION,
                "embedding_code_revision": EMBEDDING_CODE_REVISION,
                "binary_verdict": True,
                "retrieval_top_k": 5,
                "question_count": 10,
                "decoding_seed": 11,
                "llm_cache_keys": {
                    "plan": [item["cache_key"] for item in plan_receipts],
                    "answers": [item["cache_key"] for item in answer_receipts],
                    "verdict": [item["cache_key"] for item in verdict_receipts],
                },
                "attack_approximation": "reuse exact nested 1% attacker-specific prefix",
            },
        }
        artifact = normalize_record(record, task)
        stored_path, cached = store_immutable(endpoint_root, artifact)
        trace = {
            "trace_schema_version": 1,
            "task_key": task["task_key"],
            "task": task,
            "attacker_model_id": attacker_id,
            "victim_model_id": victim_id,
            "source_poison_material": str(material_path),
            "source_poison_documents_sha256": material["documents_sha256"],
            "plan": plan,
            "answers": answers,
            "verdict": verdict,
            "retrievals": [
                [
                    {
                        "document_id": result["document_id"],
                        "is_poison": result["is_poison"],
                        "rank": rank,
                        "distance": result["distance"],
                        "text_sha256": hashlib.sha256(
                            result["text"].encode("utf-8")
                        ).hexdigest(),
                        "text_excerpt": result["text"][: args.evidence_chars],
                    }
                    for rank, result in enumerate(group, 1)
                ]
                for group in retrievals
            ],
            "llm_receipts": {
                "plan": plan_receipts,
                "answers": answer_receipts,
                "verdict": verdict_receipts,
            },
            "artifact_path": str(stored_path),
        }
        atomic_json(trace_path, trace)
        return {
            "task_key": task["task_key"],
            "artifact_path": str(stored_path),
            "trace_path": str(trace_path),
            "cached_artifact": cached,
            "reused_diagonal": False,
        }

    successes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(execute, *job): job for job in jobs}
        for completed, future in enumerate(concurrent.futures.as_completed(futures), 1):
            attacker_id, victim_id, claim_id = futures[future]
            try:
                result = future.result()
                successes.append(
                    {
                        "attacker_model_id": attacker_id,
                        "victim_model_id": victim_id,
                        "claim_id": claim_id,
                        "condition_id": CONDITION,
                        **result,
                    }
                )
            except Exception as exc:
                failures.append(
                    {
                        "attacker_model_id": attacker_id,
                        "victim_model_id": victim_id,
                        "claim_id": claim_id,
                        "error": repr(exc),
                        "traceback": traceback.format_exc(),
                    }
                )
            if completed % 10 == 0 or completed == len(jobs):
                successes.sort(
                    key=lambda row: (
                        row["attacker_model_id"],
                        row["victim_model_id"],
                        row["claim_id"],
                    )
                )
                atomic_json(
                    manifest_path,
                    {
                        "experiment_id": args.experiment_id,
                        "split": runner.active_split,
                        "condition_id": CONDITION,
                        "rate": RATE,
                        "attackers": list(ATTACKERS),
                        "victims": list(VICTIMS),
                        "common_claim_ids": common_claims,
                        "requested": len(jobs),
                        "successes": successes,
                        "failures": failures,
                    },
                )
                ledger.update(
                    status="running" if not failures else "failed",
                    phase="crossed_endpoints",
                    event="attacker_transfer_progress",
                    counts={
                        "expected": len(jobs),
                        "completed": len(successes),
                        "failed": len(failures),
                        "cached": sum(bool(row["cached_artifact"]) for row in successes),
                    },
                    artifacts={"manifest": str(manifest_path)},
                )
                print(
                    f"transfer {completed}/{len(jobs)} completed={len(successes)} "
                    f"failures={len(failures)}"
                )
    status = "complete" if not failures and len(successes) == len(jobs) else "failed"
    ledger.update(
        status=status,
        phase="crossed_endpoints",
        event=f"attacker_transfer_{status}",
        counts={"expected": len(jobs), "completed": len(successes), "failed": len(failures)},
        artifacts={"manifest": str(manifest_path)},
    )
    print(
        json.dumps(
            {
                "status": status,
                "jointly_eligible_claims": len(common_claims),
                "outputs": len(successes),
                "failures": len(failures),
            },
            indent=2,
        )
    )
    if status != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
