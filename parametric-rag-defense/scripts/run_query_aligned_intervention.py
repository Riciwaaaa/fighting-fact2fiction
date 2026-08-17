#!/usr/bin/env python3
"""Remove query-aligned suspect documents from fixed context and rerun RAG reasoning."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import traceback
from pathlib import Path
from typing import Any, Callable

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import LLMCache, canonical_json
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.query_aligned_internal import (
    eligible_conflict_indices,
    filter_suspect_documents,
    suspect_document_ids,
)
from parametric_rag_defense.workflow_runtime import store_immutable_output
from run_stage1_rag_scan import (
    assert_neutral_victim_prompt,
    cached_structured_call,
    mask_urls,
    neutral_evidence_id,
    parse_answers,
    parse_verdict,
    render,
)

INTERVENTION_VERSION = "query-aligned-fixed-context-removal-v1"


def execute_jobs(
    jobs: list[tuple[str, Callable[[], dict[str, Any]]]],
    *,
    workers: int,
    phase: str,
    ledger: ExperimentLedger,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    completed = {}
    failures = []
    ledger.update(
        status="running",
        phase=phase,
        event=f"{phase}_started",
        counts={"expected": len(jobs), "completed": 0, "failed": 0},
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(function): identity for identity, function in jobs}
        for count, future in enumerate(concurrent.futures.as_completed(futures), 1):
            identity = futures[future]
            try:
                completed[identity] = future.result()
                print(
                    f"{phase} {count}/{len(jobs)} identity={identity} "
                    f"cached={completed[identity].get('cache_hit')}"
                )
            except Exception as exc:
                failure = {
                    "phase": phase,
                    "identity": identity,
                    "error_type": type(exc).__name__,
                    "error": repr(exc),
                    "traceback": traceback.format_exc(),
                }
                failures.append(failure)
                print(f"{phase} {count}/{len(jobs)} FAILED identity={identity}: {exc}")
            if count % 10 == 0 or count == len(jobs):
                ledger.update(
                    status="failed" if failures else "running",
                    phase=phase,
                    event=f"{phase}_progress",
                    counts={
                        "expected": len(jobs),
                        "completed": len(completed),
                        "failed": len(failures),
                    },
                )
    return completed, failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--protocol", type=Path, default=Path("configs/query_aligned_intervention_v1.json")
    )
    parser.add_argument(
        "--conflict-manifest",
        type=Path,
        default=Path(
            "artifacts/runs/query_aligned/query_aligned_conflict_map_v1/private_manifest.json"
        ),
    )
    parser.add_argument(
        "--trace-root",
        type=Path,
        default=Path(
            "artifacts/runs/stage1/development/rag/stage1_rag_v1.2/private_traces"
        ),
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()

    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    decoding = protocol["decoding"]
    load_dotenv(config_path.parent.parent / ".env")
    cache = LLMCache(Path(config["cache_root"]).resolve())
    models = {model["id"]: model for model in config["models"] if model.get("enabled")}
    dataset = json.loads(Path(config["dataset"]["source"]).read_text(encoding="utf-8"))
    conflict_manifest = json.loads(args.conflict_manifest.read_text(encoding="utf-8"))
    if conflict_manifest.get("failures") or len(conflict_manifest.get("rows", [])) != protocol[
        "scope"
    ]["source_rows"]:
        raise ValueError("Conflict map is incomplete")

    answer_template = Path("prompts/rag_answers_v1.md").read_text(encoding="utf-8")
    verdict_template = Path("prompts/rag_verdict_v1.md").read_text(encoding="utf-8")
    output_cache = {}
    prepared = []
    for descriptor in conflict_manifest["rows"]:
        conflict_output = output_cache.setdefault(
            descriptor["output_path"],
            json.loads(Path(descriptor["output_path"]).read_text(encoding="utf-8")),
        )
        task_key = descriptor["rag_task_key"]
        trace_path = args.trace_root / task_key[:2] / f"{task_key}.json"
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        conflict_indices = eligible_conflict_indices(conflict_output["judgment"], trace)
        if not conflict_indices:
            continue
        suspect_ids = suspect_document_ids(conflict_output["judgment"], trace)
        filtered_retrievals = filter_suspect_documents(trace["retrievals"], suspect_ids)
        identity = hashlib.sha256(
            canonical_json(
                {
                    "intervention_version": INTERVENTION_VERSION,
                    "rag_task_key": task_key,
                    "conflict_output_key": conflict_output["output_key"],
                    "suspect_document_ids": sorted(suspect_ids),
                }
            ).encode()
        ).hexdigest()
        removed = [
            item
            for group in trace["retrievals"]
            for item in group
            if str(item["document_id"]) in suspect_ids
        ]
        prepared.append(
            {
                **descriptor,
                "intervention_key": identity,
                "trace": trace,
                "conflict_output_key": conflict_output["output_key"],
                "eligible_conflict_indices": conflict_indices,
                "suspect_document_ids": sorted(suspect_ids),
                "removed_occurrences": len(removed),
                "removed_poison_document_ids": sorted(
                    {str(item["document_id"]) for item in removed if bool(item["is_poison"])}
                ),
                "filtered_retrievals": filtered_retrievals,
            }
        )
    if len(prepared) != protocol["scope"]["flagged_rows"]:
        raise ValueError(
            f"Protocol expected {protocol['scope']['flagged_rows']} interventions, found {len(prepared)}"
        )

    preparation = {
        "experiment_id": protocol["experiment_id"],
        "source_rows": protocol["scope"]["source_rows"],
        "intervention_rows": len(prepared),
        "maximum_answer_calls_before_repairs": len(prepared),
        "maximum_verdict_calls_before_repairs": len(prepared),
        "models": sorted({row["victim_model_id"] for row in prepared}),
        "new_retrieval_calls": 0,
    }
    if args.prepare_only:
        print(json.dumps(preparation, indent=2, sort_keys=True))
        return

    run_root = Path("artifacts/runs/query_aligned") / protocol["experiment_id"]
    packet_root = run_root / "private_interventions"
    output_root = run_root / "outputs"
    ledger = ExperimentLedger(
        Path("artifacts/runs/progress"),
        protocol["experiment_id"],
        description="Fixed-context removal of query-aligned suspect document identities",
    )
    for item in prepared:
        private_record = {
            "intervention_schema_version": 1,
            "intervention_version": INTERVENTION_VERSION,
            "intervention_key": item["intervention_key"],
            "rag_task_key": item["rag_task_key"],
            "victim_model_id": item["victim_model_id"],
            "claim_id": item["claim_id"],
            "condition_id": item["condition_id"],
            "conflict_output_key": item["conflict_output_key"],
            "eligible_conflict_indices": item["eligible_conflict_indices"],
            "suspect_document_ids": item["suspect_document_ids"],
            "removed_occurrences": item["removed_occurrences"],
            "removed_poison_document_ids": item["removed_poison_document_ids"],
            "retrieval_group_sizes_before": [len(group) for group in item["trace"]["retrievals"]],
            "retrieval_group_sizes_after": [len(group) for group in item["filtered_retrievals"]],
        }
        path, _ = store_immutable_output(
            packet_root, item["intervention_key"], private_record
        )
        item["intervention_path"] = str(path)

    answer_jobs = []
    for item in prepared:
        claim = dataset[int(item["claim_id"])]
        claim_record = (
            f"Text: {mask_urls(claim['claim'])}\n"
            f"Claim date: {mask_urls(claim.get('claim_date') or 'unknown')}"
        )
        blocks = []
        for index, (question, results) in enumerate(
            zip(item["trace"]["plan"]["questions"], item["filtered_retrievals"])
        ):
            blocks.append(
                {
                    "question_index": index,
                    "question": question["question"],
                    "results": [
                        {
                            "rank": rank,
                            "source_id": neutral_evidence_id(index, rank),
                            "text": mask_urls(
                                result["text_excerpt"][: protocol["intervention"]["evidence_chars"]]
                            ),
                        }
                        for rank, result in enumerate(results, 1)
                    ],
                }
            )
        prompt = render(
            answer_template,
            {
                "CLAIM_RECORD": claim_record,
                "RETRIEVAL_RECORD": json.dumps(blocks, ensure_ascii=False),
            },
        )
        assert_neutral_victim_prompt(prompt)
        model = models[item["victim_model_id"]]

        def answer_job(
            item: dict[str, Any] = item,
            model: dict[str, Any] = model,
            prompt: str = prompt,
        ) -> dict[str, Any]:
            judgment, receipts = cached_structured_call(
                cache,
                model,
                stage="stage1_rag_answers",
                prompt_id="rag_answers_v1",
                prompt=prompt,
                parser=lambda text: parse_answers(
                    text, [len(group) for group in item["filtered_retrievals"]]
                ),
                temperature=decoding["temperature"],
                top_p=decoding["top_p"],
                max_tokens=decoding["max_answer_tokens"],
                seed=decoding["seed"],
                metadata={
                    "role": "query_aligned_fixed_context_answers",
                    "intervention_key": item["intervention_key"],
                    "model_id": item["victim_model_id"],
                    "claim_id": item["claim_id"],
                },
                contract_retries=decoding["contract_retries"],
            )
            return {
                "judgment": judgment,
                "receipts": receipts,
                "cache_hit": receipts[-1]["cache_hit"],
            }

        answer_jobs.append((item["intervention_key"], answer_job))

    answers, answer_failures = execute_jobs(
        answer_jobs, workers=args.workers, phase="intervention_answers", ledger=ledger
    )
    verdict_jobs = []
    for item in prepared:
        if item["intervention_key"] not in answers:
            continue
        answer_output = answers[item["intervention_key"]]
        claim = dataset[int(item["claim_id"])]
        claim_record = (
            f"Text: {mask_urls(claim['claim'])}\n"
            f"Claim date: {mask_urls(claim.get('claim_date') or 'unknown')}"
        )
        qa_record = []
        for question_index, (question, answer, results) in enumerate(
            zip(
                item["trace"]["plan"]["questions"],
                answer_output["judgment"]["answers"],
                item["filtered_retrievals"],
            )
        ):
            selected = None
            if answer["selected_rank"] is not None:
                result = results[answer["selected_rank"] - 1]
                selected = {
                    "source_id": neutral_evidence_id(
                        question_index, answer["selected_rank"]
                    ),
                    "text": mask_urls(
                        result["text_excerpt"][: protocol["intervention"]["selected_verdict_evidence_chars"]]
                    ),
                }
            qa_record.append(
                {
                    "question": mask_urls(question["question"]),
                    "answer": mask_urls(answer["answer"]),
                    "selected_evidence": selected,
                }
            )
        prompt = render(
            verdict_template,
            {
                "CLAIM_RECORD": claim_record,
                "QA_RECORD": json.dumps(qa_record, ensure_ascii=False),
            },
        )
        assert_neutral_victim_prompt(prompt)
        model = models[item["victim_model_id"]]

        def verdict_job(
            item: dict[str, Any] = item,
            model: dict[str, Any] = model,
            prompt: str = prompt,
            answer_output: dict[str, Any] = answer_output,
        ) -> dict[str, Any]:
            judgment, receipts = cached_structured_call(
                cache,
                model,
                stage="stage1_rag_verdict",
                prompt_id="rag_verdict_v1",
                prompt=prompt,
                parser=parse_verdict,
                temperature=decoding["temperature"],
                top_p=decoding["top_p"],
                max_tokens=decoding["max_verdict_tokens"],
                seed=decoding["seed"],
                metadata={
                    "role": "query_aligned_fixed_context_verdict",
                    "intervention_key": item["intervention_key"],
                    "model_id": item["victim_model_id"],
                    "claim_id": item["claim_id"],
                },
                contract_retries=decoding["contract_retries"],
            )
            output = {
                "output_schema_version": 1,
                "intervention_version": INTERVENTION_VERSION,
                "intervention_key": item["intervention_key"],
                "rag_task_key": item["rag_task_key"],
                "answers": answer_output["judgment"],
                "verdict": judgment,
                "answer_receipts": answer_output["receipts"],
                "verdict_receipts": receipts,
            }
            path = output_root / item["intervention_key"][:2] / f"{item['intervention_key']}.json"
            if path.exists():
                stored = json.loads(path.read_text(encoding="utf-8"))
                if (
                    stored.get("intervention_key") != item["intervention_key"]
                    or stored.get("answers") != answer_output["judgment"]
                    or stored.get("verdict") != judgment
                ):
                    raise RuntimeError(f"Existing intervention output does not match: {path}")
                artifact_hit = True
            else:
                path, artifact_hit = store_immutable_output(
                    output_root, item["intervention_key"], output
                )
            return {
                "output_path": str(path),
                "artifact_hit": artifact_hit,
                "cache_hit": receipts[-1]["cache_hit"],
                "verdict": judgment["verdict"],
                "answer_receipts": answer_output["receipts"],
                "verdict_receipts": receipts,
            }

        verdict_jobs.append((item["intervention_key"], verdict_job))

    verdicts, verdict_failures = execute_jobs(
        verdict_jobs, workers=args.workers, phase="intervention_verdicts", ledger=ledger
    )
    failures = answer_failures + verdict_failures
    manifest_rows = []
    for item in prepared:
        result = verdicts.get(item["intervention_key"])
        if result is None:
            continue
        manifest_rows.append(
            {
                "intervention_key": item["intervention_key"],
                "victim_model_id": item["victim_model_id"],
                "claim_id": item["claim_id"],
                "condition_id": item["condition_id"],
                "rag_task_key": item["rag_task_key"],
                "conflict_output_key": item["conflict_output_key"],
                "eligible_conflict_indices": item["eligible_conflict_indices"],
                "suspect_document_ids": item["suspect_document_ids"],
                "removed_poison_document_ids": item["removed_poison_document_ids"],
                "intervention_path": item["intervention_path"],
                **result,
            }
        )
    manifest = {
        "manifest_schema_version": 1,
        **preparation,
        "completed_outputs": len(manifest_rows),
        "failures": failures,
        "rows": sorted(
            manifest_rows,
            key=lambda row: (
                row["claim_id"], row["victim_model_id"], row["condition_id"]
            ),
        ),
    }
    manifest_path = run_root / "private_manifest.json"
    atomic_json(manifest_path, manifest)
    complete = not failures and len(manifest_rows) == len(prepared)
    ledger.update(
        status="complete" if complete else "failed",
        phase="complete" if complete else "intervention",
        event="query_aligned_intervention_finished",
        counts={
            "expected": len(prepared),
            "completed": len(manifest_rows),
            "failed": len(failures),
        },
        artifacts={"private_manifest": str(manifest_path)},
    )
    print(json.dumps({**preparation, "completed": len(manifest_rows), "failed": len(failures)}, indent=2))
    if not complete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
