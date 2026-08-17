#!/usr/bin/env python3
"""Rerun unchanged RAG reasoning over deterministic fixed-retrieval stress views."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import LLMCache, canonical_json
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.rag_stress import (
    STRESS_VIEW_VERSION,
    assertion_units,
    build_stress_views,
    parse_stress_answers,
    passage_document_map,
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


def row_identity(row: dict[str, Any]) -> tuple[str, int, str]:
    return row["victim_model_id"], int(row["claim_id"]), row["condition_id"]


def execute_jobs(
    jobs: list[tuple[str, Callable[[], dict[str, Any]]]], *, workers: int, phase: str,
    ledger: ExperimentLedger
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    completed: dict[str, dict[str, Any]] = {}
    failures = []
    ledger.update(
        status="running", phase=phase, event=f"{phase}_started",
        counts={"expected": len(jobs), "completed": 0, "failed": 0},
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(function): identity for identity, function in jobs}
        for count, future in enumerate(concurrent.futures.as_completed(futures), 1):
            identity = futures[future]
            try:
                completed[identity] = future.result()
            except Exception as exc:
                failures.append(
                    {
                        "phase": phase,
                        "identity": identity,
                        "error_type": type(exc).__name__,
                        "error": repr(exc),
                        "traceback": traceback.format_exc(),
                        "receipts": getattr(exc, "receipts", None),
                    }
                )
            if count % 10 == 0 or count == len(jobs):
                print(f"{phase} {count}/{len(jobs)} failures={len(failures)}")
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
        "--protocol", type=Path, default=Path("configs/rag_cluster_stress_v1.json")
    )
    parser.add_argument(
        "--source-root", type=Path,
        default=Path("artifacts/runs/evidence_signal/evidence_signal_v1"),
    )
    parser.add_argument(
        "--trace-root", type=Path,
        default=Path("artifacts/runs/stage1/development/rag/stage1_rag_v1.2/private_traces"),
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        raise SystemExit("workers must be positive")

    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    decoding = protocol["decoding"]
    source_manifest = json.loads(
        (args.source_root / "private_manifest.json").read_text(encoding="utf-8")
    )
    if source_manifest.get("failures") or source_manifest.get("completed_outputs") != protocol[
        "scope"
    ]["source_rows"]:
        raise ValueError("Evidence-signal source is incomplete or differs from frozen scope")
    dataset = json.loads(Path(config["dataset"]["source"]).read_text(encoding="utf-8"))
    models = {model["id"]: model for model in config["models"] if model.get("enabled")}
    answer_template = Path("prompts/rag_answers_v1.md").read_text(encoding="utf-8")
    verdict_template = Path("prompts/rag_verdict_v1.md").read_text(encoding="utf-8")

    named_views = []
    execution_cases: dict[str, dict[str, Any]] = {}
    for descriptor in source_manifest["rows"]:
        packet = json.loads(Path(descriptor["packet_path"]).read_text(encoding="utf-8"))
        endpoint = json.loads(Path(descriptor["endpoint_path"]).read_text(encoding="utf-8"))
        evidence_output = json.loads(
            Path(descriptor["output_path"]).read_text(encoding="utf-8")
        )
        trace_path = args.trace_root / descriptor["rag_task_key"][:2] / (
            descriptor["rag_task_key"] + ".json"
        )
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        alias_documents = passage_document_map(
            packet_visible=packet["visible"],
            endpoint_judgment=endpoint["judgment"],
            trace=trace,
        )
        units = assertion_units(
            evidence_judgment=evidence_output["judgment"],
            alias_documents=alias_documents,
        )
        views = build_stress_views(
            task_key=descriptor["rag_task_key"],
            rag_prediction=descriptor["retrieval_prediction"],
            units=units,
            retrievals=trace["retrievals"],
        )
        if len(views) < 2:
            raise ValueError(f"Stress construction has fewer than two views: {row_identity(descriptor)}")
        claim = dataset[int(descriptor["claim_id"])]
        claim_record = (
            f"Text: {mask_urls(claim['claim'])}\n"
            f"Claim date: {mask_urls(claim.get('claim_date') or 'unknown')}"
        )
        original_poison_ids = {
            str(item["document_id"])
            for group in trace["retrievals"]
            for item in group
            if bool(item["is_poison"])
        }
        unit_public = [
            {
                "unit_id": unit["unit_id"],
                "kind": unit["kind"],
                "passage_count": len(unit["passage_ids"]),
                "document_count": len(unit["document_ids"]),
                "stance": unit["stance"],
                "directness": unit["directness"],
            }
            for unit in units
        ]
        for view in views:
            blocks = []
            for index, (question, results) in enumerate(
                zip(trace["plan"]["questions"], view["retrievals"])
            ):
                blocks.append(
                    {
                        "question_index": index,
                        "question": mask_urls(question["question"]),
                        "results": [
                            {
                                "rank": rank,
                                "source_id": neutral_evidence_id(index, rank),
                                "text": mask_urls(
                                    result["text_excerpt"][: protocol["context"]["evidence_chars"]]
                                ),
                            }
                            for rank, result in enumerate(results, 1)
                        ],
                    }
                )
            answer_prompt = render(
                answer_template,
                {
                    "CLAIM_RECORD": claim_record,
                    "RETRIEVAL_RECORD": json.dumps(blocks, ensure_ascii=False),
                },
            )
            assert_neutral_victim_prompt(answer_prompt)
            execution_key = hashlib.sha256(
                canonical_json(
                    {
                        "stress_view_version": STRESS_VIEW_VERSION,
                        "victim_model_id": descriptor["victim_model_id"],
                        "answer_prompt_sha256": hashlib.sha256(
                            answer_prompt.encode("utf-8")
                        ).hexdigest(),
                    }
                ).encode()
            ).hexdigest()
            case = {
                "execution_key": execution_key,
                "victim_model_id": descriptor["victim_model_id"],
                "claim_id": int(descriptor["claim_id"]),
                "claim_record": claim_record,
                "plan": trace["plan"],
                "retrievals": view["retrievals"],
                "answer_prompt": answer_prompt,
            }
            existing = execution_cases.setdefault(execution_key, case)
            if (
                existing["victim_model_id"] != case["victim_model_id"]
                or existing["answer_prompt"] != case["answer_prompt"]
            ):
                raise ValueError(f"Conflicting execution case: {execution_key}")
            view_key = hashlib.sha256(
                canonical_json(
                    {
                        "stress_view_version": STRESS_VIEW_VERSION,
                        "rag_task_key": descriptor["rag_task_key"],
                        "view_type": view["view_type"],
                        "context_key": view["context_key"],
                    }
                ).encode()
            ).hexdigest()
            named_views.append(
                {
                    "view_key": view_key,
                    "execution_key": execution_key,
                    "victim_model_id": descriptor["victim_model_id"],
                    "claim_id": int(descriptor["claim_id"]),
                    "condition_id": descriptor["condition_id"],
                    "rag_task_key": descriptor["rag_task_key"],
                    "original_rag_prediction": descriptor["retrieval_prediction"],
                    "memory_prediction": descriptor["memory_prediction"],
                    "source_packet_key": packet["packet_key"],
                    "source_evidence_output_key": evidence_output["output_key"],
                    "view_type": view["view_type"],
                    "context_key": view["context_key"],
                    "retained_unit_ids": view["retained_unit_ids"],
                    "removed_unit_ids": view["removed_unit_ids"],
                    "unit_structure": unit_public,
                    "retained_document_count": len(view["retained_document_ids"]),
                    "removed_document_count": len(view["removed_document_ids"]),
                    "retained_poison_document_ids": sorted(
                        original_poison_ids & set(view["retained_document_ids"])
                    ),
                    "removed_poison_document_ids": sorted(
                        original_poison_ids & set(view["removed_document_ids"])
                    ),
                }
            )

    view_keys = [row["view_key"] for row in named_views]
    if len(view_keys) != len(set(view_keys)):
        raise ValueError("Named stress-view keys are not unique")
    counts = Counter(row["view_type"] for row in named_views)
    preparation = {
        "experiment_id": protocol["experiment_id"],
        "stress_view_version": STRESS_VIEW_VERSION,
        "source_rows": protocol["scope"]["source_rows"],
        "named_views": len(named_views),
        "unique_execution_cases": len(execution_cases),
        "maximum_answer_calls_before_repairs": len(execution_cases),
        "maximum_verdict_calls_before_repairs": len(execution_cases),
        "new_retrieval_calls": 0,
        "backfill_calls": 0,
        "view_type_counts": dict(sorted(counts.items())),
        "models": sorted({row["victim_model_id"] for row in named_views}),
    }
    if preparation["named_views"] != protocol["scope"]["named_views"]:
        raise ValueError("Named view count differs from frozen protocol")
    if (
        protocol["scope"]["unique_execution_cases"] is not None
        and preparation["unique_execution_cases"]
        != protocol["scope"]["unique_execution_cases"]
    ):
        raise ValueError("Unique execution count differs from frozen protocol")
    if args.prepare_only:
        print(json.dumps(preparation, indent=2, sort_keys=True))
        return

    load_dotenv(config_path.parent.parent / ".env")
    cache = LLMCache(Path(config["cache_root"]).resolve())
    run_root = Path("artifacts/runs/rag_stress") / protocol["experiment_id"]
    output_root = run_root / "outputs"
    ledger = ExperimentLedger(
        Path("artifacts/runs/progress"), protocol["experiment_id"],
        description="Fixed-retrieval assertion-cluster RAG stress test",
    )

    answer_jobs = []
    for execution_key, case in sorted(execution_cases.items()):
        model = models[case["victim_model_id"]]

        def answer_job(
            execution_key: str = execution_key, case: dict[str, Any] = case,
            model: dict[str, Any] = model
        ) -> dict[str, Any]:
            judgment, receipts = cached_structured_call(
                cache, model,
                stage="stage1_rag_answers",
                prompt_id="rag_answers_v1",
                prompt=case["answer_prompt"],
                parser=lambda text: parse_stress_answers(
                    text,
                    result_counts=[len(group) for group in case["retrievals"]],
                    base_parser=parse_answers,
                ),
                temperature=decoding["temperature"], top_p=decoding["top_p"],
                max_tokens=decoding["max_answer_tokens"], seed=decoding["seed"],
                metadata={
                    "role": "fixed_assertion_cluster_stress_answers",
                    "execution_key": execution_key,
                    "model_id": case["victim_model_id"],
                    "claim_id": case["claim_id"],
                },
                contract_retries=decoding["contract_retries"],
            )
            return {"judgment": judgment, "receipts": receipts}

        answer_jobs.append((execution_key, answer_job))
    answers, answer_failures = execute_jobs(
        answer_jobs, workers=args.workers, phase="stress_answers", ledger=ledger
    )

    verdict_jobs = []
    for execution_key, case in sorted(execution_cases.items()):
        if execution_key not in answers:
            continue
        answer_output = answers[execution_key]
        qa_record = []
        for question_index, (question, answer, results) in enumerate(
            zip(case["plan"]["questions"], answer_output["judgment"]["answers"], case["retrievals"])
        ):
            selected = None
            if answer["selected_rank"] is not None:
                result = results[answer["selected_rank"] - 1]
                selected = {
                    "source_id": neutral_evidence_id(question_index, answer["selected_rank"]),
                    "text": mask_urls(
                        result["text_excerpt"][: protocol["context"]["selected_verdict_evidence_chars"]]
                    ),
                }
            qa_record.append(
                {
                    "question": mask_urls(question["question"]),
                    "answer": mask_urls(answer["answer"]),
                    "selected_evidence": selected,
                }
            )
        verdict_prompt = render(
            verdict_template,
            {
                "CLAIM_RECORD": case["claim_record"],
                "QA_RECORD": json.dumps(qa_record, ensure_ascii=False),
            },
        )
        assert_neutral_victim_prompt(verdict_prompt)
        model = models[case["victim_model_id"]]

        def verdict_job(
            execution_key: str = execution_key, case: dict[str, Any] = case,
            answer_output: dict[str, Any] = answer_output, model: dict[str, Any] = model,
            verdict_prompt: str = verdict_prompt
        ) -> dict[str, Any]:
            existing_path = output_root / execution_key[:2] / f"{execution_key}.json"
            if existing_path.exists():
                stored = json.loads(existing_path.read_text(encoding="utf-8"))
                if (
                    stored.get("stress_view_version") != STRESS_VIEW_VERSION
                    or stored.get("execution_key") != execution_key
                    or stored.get("answers") != answer_output["judgment"]
                    or not isinstance(stored.get("verdict"), dict)
                ):
                    raise RuntimeError(
                        f"Existing stress output does not match execution: {existing_path}"
                    )
                return {
                    "output_path": str(existing_path),
                    "artifact_hit": True,
                    "answer_receipts": stored.get("answer_receipts", []),
                    "verdict_receipts": stored.get("verdict_receipts", []),
                }
            judgment, receipts = cached_structured_call(
                cache, model,
                stage="stage1_rag_verdict", prompt_id="rag_verdict_v1",
                prompt=verdict_prompt, parser=parse_verdict,
                temperature=decoding["temperature"], top_p=decoding["top_p"],
                max_tokens=decoding["max_verdict_tokens"], seed=decoding["seed"],
                metadata={
                    "role": "fixed_assertion_cluster_stress_verdict",
                    "execution_key": execution_key,
                    "model_id": case["victim_model_id"],
                    "claim_id": case["claim_id"],
                },
                contract_retries=decoding["contract_retries"],
            )
            output = {
                "output_schema_version": 1,
                "stress_view_version": STRESS_VIEW_VERSION,
                "execution_key": execution_key,
                "answers": answer_output["judgment"],
                "verdict": judgment,
                "answer_receipts": answer_output["receipts"],
                "verdict_receipts": receipts,
            }
            output_path, artifact_hit = store_immutable_output(
                output_root, execution_key, output
            )
            return {
                "output_path": str(output_path),
                "artifact_hit": artifact_hit,
                "answer_receipts": answer_output["receipts"],
                "verdict_receipts": receipts,
            }

        verdict_jobs.append((execution_key, verdict_job))
    verdicts, verdict_failures = execute_jobs(
        verdict_jobs, workers=args.workers, phase="stress_verdicts", ledger=ledger
    )
    failures = answer_failures + verdict_failures
    final_views = [
        {**row, "output_path": verdicts[row["execution_key"]]["output_path"]}
        for row in named_views
        if row["execution_key"] in verdicts
    ]
    manifest = {
        "manifest_schema_version": 1,
        **preparation,
        "completed_execution_cases": len(verdicts),
        "completed_named_views": len(final_views),
        "failures": failures,
        "views": sorted(
            final_views,
            key=lambda row: (
                row["claim_id"], row["victim_model_id"], row["condition_id"], row["view_type"]
            ),
        ),
    }
    atomic_json(run_root / "private_manifest.json", manifest)
    status = (
        "complete"
        if not failures and len(verdicts) == len(execution_cases) and len(final_views) == len(named_views)
        else "failed"
    )
    ledger.update(
        status=status, phase="stress_verdicts",
        event="stress_completed" if status == "complete" else "stress_failed",
        counts={
            "expected": len(execution_cases),
            "completed": len(verdicts),
            "failed": len(failures),
        },
        artifacts={"manifest": str(run_root / "private_manifest.json")},
    )
    print(json.dumps({"status": status, **preparation, "failures": len(failures)}, indent=2))
    if status != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
