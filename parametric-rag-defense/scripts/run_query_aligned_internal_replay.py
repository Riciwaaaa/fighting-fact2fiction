#!/usr/bin/env python3
"""Collect two cached closed-book answers to every exact RAG question plan."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import traceback
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import LLMCache, LLMRequest, canonical_json
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.query_aligned_internal import (
    REPLAY_CONTRACT_VERSION,
    parse_internal_question_answers,
    replay_case_key,
)
from parametric_rag_defense.workflow_runtime import (
    execute_cached,
    prompt_version,
    render,
    store_immutable_output,
)


def load_cases(
    source_manifest: Path, trace_root: Path, dataset_path: Path
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases: dict[str, dict[str, Any]] = {}
    source_rows = []
    model_claim_keys: dict[tuple[str, int], str] = {}
    for row in manifest["rows"]:
        task_key = row["rag_task_key"]
        trace_path = trace_root / task_key[:2] / f"{task_key}.json"
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        questions = [str(item["question"]).strip() for item in trace["plan"]["questions"]]
        claim_id = int(row["claim_id"])
        model_id = str(row["victim_model_id"])
        claim_date = str(dataset[claim_id].get("claim_date") or "unknown")
        key = replay_case_key(
            model_id=model_id,
            claim_id=claim_id,
            claim_date=claim_date,
            questions=questions,
        )
        identity = (model_id, claim_id)
        previous = model_claim_keys.setdefault(identity, key)
        if previous != key:
            raise ValueError(f"Question plan changed across conditions for {identity}")
        case = {
            "case_key": key,
            "victim_model_id": model_id,
            "claim_id": claim_id,
            "claim_date": claim_date,
            "questions": questions,
        }
        existing = cases.setdefault(key, case)
        if existing != case:
            raise ValueError(f"Replay case collision: {key}")
        source_rows.append(
            {
                "victim_model_id": model_id,
                "claim_id": claim_id,
                "condition_id": row["condition_id"],
                "rag_task_key": task_key,
                "case_key": key,
            }
        )
    return cases, source_rows


def output_key(case_key: str, repeat_index: int, cache_key: str) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "output_schema_version": 1,
                "case_key": case_key,
                "repeat_index": repeat_index,
                "cache_key": cache_key,
            }
        ).encode()
    ).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--protocol", type=Path, default=Path("configs/query_aligned_internal_replay_v1.json")
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=Path(
            "artifacts/runs/counter_retrieval/counter_retrieval_signal_v2/private_manifest.json"
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
    if args.workers < 1:
        raise SystemExit("workers must be positive")
    load_dotenv(config_path.parent.parent / ".env")
    models = {model["id"]: model for model in config["models"] if model.get("enabled")}
    cases, source_rows = load_cases(
        args.source_manifest,
        args.trace_root,
        Path(config["dataset"]["source"]),
    )
    if len(cases) != protocol["scope"]["expected_unique_cases"]:
        raise ValueError(
            f"Protocol expected {protocol['scope']['expected_unique_cases']} cases, found {len(cases)}"
        )
    if any(len(case["questions"]) != protocol["scope"]["questions_per_case"] for case in cases.values()):
        raise ValueError("A replay case does not contain the frozen question count")
    for case in cases.values():
        if case["victim_model_id"] not in models:
            raise ValueError(f"Unavailable model: {case['victim_model_id']}")

    preparation = {
        "experiment_id": protocol["experiment_id"],
        "source_rows": len(source_rows),
        "unique_cases": len(cases),
        "repeats": decoding["repeats"],
        "maximum_calls_before_contract_repairs": len(cases) * decoding["repeats"],
        "models": sorted({case["victim_model_id"] for case in cases.values()}),
    }
    if args.prepare_only:
        print(json.dumps(preparation, indent=2, sort_keys=True))
        return

    prompt_template, prompt_digest = prompt_version(
        Path("prompts/internal_rag_questions_v1.md"), "internal_rag_questions_v1"
    )
    cache = LLMCache(Path(config["cache_root"]).resolve())
    run_root = Path("artifacts/runs/query_aligned") / protocol["experiment_id"]
    output_root = run_root / "replays"
    ledger = ExperimentLedger(
        Path("artifacts/runs/progress"),
        protocol["experiment_id"],
        description="Same-model closed-book replay of the exact RAG question plans",
    )
    ledger.update(
        status="running",
        phase="replay",
        event="query_aligned_replay_started",
        counts={"expected": preparation["maximum_calls_before_contract_repairs"], "completed": 0, "failed": 0},
        details=preparation,
    )

    jobs = []
    for case_key, case in sorted(cases.items()):
        model = models[case["victim_model_id"]]
        questions_record = [
            {"question_index": index, "question": question}
            for index, question in enumerate(case["questions"])
        ]
        prompt = render(
            prompt_template,
            {
                "CLAIM_DATE": case["claim_date"],
                "QUESTIONS": json.dumps(questions_record, ensure_ascii=False),
            },
        )
        for repeat_index, seed in enumerate(decoding["seeds"]):
            request = LLMRequest(
                stage="query_aligned_internal_replay",
                provider=model["provider"],
                model=model["model"],
                prompt_id="internal_rag_questions_v1",
                prompt_version=prompt_digest,
                messages=[{"role": "user", "content": prompt}],
                parameters={
                    "temperature": decoding["temperature"],
                    "top_p": decoding["top_p"],
                    "max_tokens": decoding["max_tokens"],
                    "seed": seed,
                    **model.get("request_parameters", {}),
                },
                response_format={"type": "json_object"},
            )

            def job(
                case: dict[str, Any] = case,
                case_key: str = case_key,
                repeat_index: int = repeat_index,
                request: LLMRequest = request,
            ) -> dict[str, Any]:
                parsed, receipts = execute_cached(
                    cache=cache,
                    request=request,
                    parser=lambda text: parse_internal_question_answers(
                        text, expected_questions=len(case["questions"])
                    ),
                    metadata={
                        "role": "query_aligned_internal_replay",
                        "case_key": case_key,
                        "model_id": case["victim_model_id"],
                        "claim_id": case["claim_id"],
                        "repeat_index": repeat_index,
                    },
                    contract_name="query-aligned internal answer contract",
                    retries=decoding["contract_retries"],
                )
                identity = output_key(case_key, repeat_index, receipts[-1]["cache_key"])
                output = {
                    "output_schema_version": 1,
                    "contract_version": REPLAY_CONTRACT_VERSION,
                    "output_key": identity,
                    "case_key": case_key,
                    "victim_model_id": case["victim_model_id"],
                    "claim_id": case["claim_id"],
                    "repeat_index": repeat_index,
                    "seed": decoding["seeds"][repeat_index],
                    "judgment": parsed,
                    "receipts": receipts,
                }
                path, artifact_hit = store_immutable_output(output_root, identity, output)
                return {
                    "case_key": case_key,
                    "victim_model_id": case["victim_model_id"],
                    "claim_id": case["claim_id"],
                    "repeat_index": repeat_index,
                    "output_key": identity,
                    "output_path": str(path),
                    "cache_key": receipts[-1]["cache_key"],
                    "cache_hit": receipts[-1]["cache_hit"],
                    "artifact_hit": artifact_hit,
                    "receipts": receipts,
                }

            jobs.append(((case_key, repeat_index), job))

    completed: dict[tuple[str, int], dict[str, Any]] = {}
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_jobs = {executor.submit(function): identity for identity, function in jobs}
        for count, future in enumerate(concurrent.futures.as_completed(future_jobs), 1):
            identity = future_jobs[future]
            try:
                completed[identity] = future.result()
                print(f"replay {count}/{len(jobs)} identity={identity} cached={completed[identity]['cache_hit']}")
            except Exception as exc:
                failure = {
                    "identity": repr(identity),
                    "error_type": type(exc).__name__,
                    "error": repr(exc),
                    "traceback": traceback.format_exc(),
                }
                receipts = getattr(exc, "receipts", None)
                if receipts is not None:
                    failure["receipts"] = receipts
                failures.append(failure)
                print(f"replay {count}/{len(jobs)} FAILED identity={identity}: {exc}")
            if count % 10 == 0 or count == len(jobs):
                ledger.update(
                    status="failed" if failures else "running",
                    phase="replay",
                    event="query_aligned_replay_progress",
                    counts={"expected": len(jobs), "completed": len(completed), "failed": len(failures)},
                )

    manifest = {
        "manifest_schema_version": 1,
        **preparation,
        "prompt_version": prompt_digest,
        "completed_outputs": len(completed),
        "failures": failures,
        "cases": list(sorted(cases.values(), key=lambda value: value["case_key"])),
        "source_rows": source_rows,
        "outputs": [completed[key] for key in sorted(completed)],
    }
    manifest_path = run_root / "private_manifest.json"
    atomic_json(manifest_path, manifest)
    ledger.update(
        status="failed" if failures or len(completed) != len(jobs) else "complete",
        phase="complete" if not failures else "replay",
        event="query_aligned_replay_finished",
        counts={"expected": len(jobs), "completed": len(completed), "failed": len(failures)},
        artifacts={"private_manifest": str(manifest_path)},
    )
    print(json.dumps({**preparation, "completed": len(completed), "failed": len(failures)}, indent=2))
    if failures or len(completed) != len(jobs):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
