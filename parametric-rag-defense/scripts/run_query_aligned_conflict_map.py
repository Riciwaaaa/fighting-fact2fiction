#!/usr/bin/env python3
"""Compare cached internal question answers with the matching RAG answers."""

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
    CONFLICT_MAP_CONTRACT_VERSION,
    parse_question_conflict_map,
)
from parametric_rag_defense.workflow_runtime import (
    execute_cached,
    prompt_version,
    render,
    store_immutable_output,
)


def load_replays(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_case: dict[str, list[dict[str, Any]]] = {}
    for descriptor in manifest["outputs"]:
        output = json.loads(Path(descriptor["output_path"]).read_text(encoding="utf-8"))
        by_case.setdefault(descriptor["case_key"], []).append(output)
    expected_repeats = int(manifest["repeats"])
    for case_key, outputs in by_case.items():
        outputs.sort(key=lambda value: value["repeat_index"])
        if [value["repeat_index"] for value in outputs] != list(range(expected_repeats)):
            raise ValueError(f"Replay coverage mismatch for case {case_key}")
    if len(by_case) != manifest["unique_cases"]:
        raise ValueError("Replay case coverage is incomplete")
    return by_case


def packet_key(visible: dict[str, Any], model_id: str, replay_keys: list[str]) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "contract_version": CONFLICT_MAP_CONTRACT_VERSION,
                "model_id": model_id,
                "visible": visible,
                "replay_output_keys": replay_keys,
            }
        ).encode()
    ).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--protocol", type=Path, default=Path("configs/query_aligned_conflict_map_v1.json")
    )
    parser.add_argument(
        "--replay-manifest",
        type=Path,
        default=Path(
            "artifacts/runs/query_aligned/query_aligned_internal_replay_v1/private_manifest.json"
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
    models = {model["id"]: model for model in config["models"] if model.get("enabled")}
    replay_manifest = json.loads(args.replay_manifest.read_text(encoding="utf-8"))
    if replay_manifest.get("failures") or replay_manifest.get("completed_outputs") != replay_manifest.get(
        "maximum_calls_before_contract_repairs"
    ):
        raise ValueError("Internal replay is incomplete")
    replays = load_replays(replay_manifest)
    case_lookup = {case["case_key"]: case for case in replay_manifest["cases"]}
    source_rows = replay_manifest["source_rows"]
    if len(source_rows) != protocol["scope"]["expected_rows"]:
        raise ValueError("Conflict-map source row count differs from frozen protocol")

    prepared = []
    for row in source_rows:
        trace_path = args.trace_root / row["rag_task_key"][:2] / f"{row['rag_task_key']}.json"
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        case = case_lookup[row["case_key"]]
        replay_outputs = replays[row["case_key"]]
        records = []
        for index, (question, rag_answer) in enumerate(
            zip(trace["plan"]["questions"], trace["answers"]["answers"])
        ):
            attempts = [
                output["judgment"]["answers"][index] for output in replay_outputs
            ]
            records.append(
                {
                    "question_index": index,
                    "question": question["question"],
                    "internal_attempts": attempts,
                    "rag_answer": {
                        "status": rag_answer["status"],
                        "answer": rag_answer["answer"],
                    },
                }
            )
        visible = {"answer_records": records}
        replay_keys = [output["output_key"] for output in replay_outputs]
        identity = packet_key(visible, row["victim_model_id"], replay_keys)
        prepared.append(
            {
                **row,
                "packet_key": identity,
                "visible": visible,
                "replay_output_keys": replay_keys,
                "questions": case["questions"],
            }
        )

    preparation = {
        "experiment_id": protocol["experiment_id"],
        "rows": len(prepared),
        "unique_packets": len({item["packet_key"] for item in prepared}),
        "maximum_calls_before_contract_repairs": len(
            {item["packet_key"] for item in prepared}
        ),
        "models": sorted({row["victim_model_id"] for row in prepared}),
    }
    if args.prepare_only:
        print(json.dumps(preparation, indent=2, sort_keys=True))
        return

    template, template_version = prompt_version(
        Path("prompts/query_answer_conflict_v1.md"), "query_answer_conflict_v1"
    )
    cache = LLMCache(Path(config["cache_root"]).resolve())
    run_root = Path("artifacts/runs/query_aligned") / protocol["experiment_id"]
    packet_root = run_root / "packets"
    output_root = run_root / "outputs"
    ledger = ExperimentLedger(
        Path("artifacts/runs/progress"),
        protocol["experiment_id"],
        description="Same-model semantic comparison of internal and RAG question answers",
    )
    ledger.update(
        status="running",
        phase="conflict_map",
        event="query_aligned_conflict_map_started",
        counts={"expected": len(prepared), "completed": 0, "failed": 0},
        details=preparation,
    )

    unique_items: dict[str, dict[str, Any]] = {}
    for item in prepared:
        existing = unique_items.setdefault(item["packet_key"], item)
        if (
            existing["visible"] != item["visible"]
            or existing["victim_model_id"] != item["victim_model_id"]
        ):
            raise ValueError(f"Conflict-map packet collision: {item['packet_key']}")

    jobs = []
    packet_paths = {}
    for item in unique_items.values():
        packet = {
            "packet_schema_version": 1,
            "contract_version": CONFLICT_MAP_CONTRACT_VERSION,
            "packet_key": item["packet_key"],
            "visible": item["visible"],
        }
        packet_path, _ = store_immutable_output(packet_root, item["packet_key"], packet)
        packet_paths[item["packet_key"]] = str(packet_path)
        model = models[item["victim_model_id"]]
        prompt = render(
            template,
            {
                "ANSWER_RECORDS": json.dumps(
                    item["visible"]["answer_records"], ensure_ascii=False, indent=2
                )
            },
        )
        request = LLMRequest(
            stage="query_aligned_answer_conflict",
            provider=model["provider"],
            model=model["model"],
            prompt_id="query_answer_conflict_v1",
            prompt_version=template_version,
            messages=[{"role": "user", "content": prompt}],
            parameters={
                "temperature": decoding["temperature"],
                "top_p": decoding["top_p"],
                "max_tokens": decoding["max_tokens"],
                "seed": decoding["seed"],
                **model.get("request_parameters", {}),
            },
            response_format={"type": "json_object"},
        )

        def job(item: dict[str, Any] = item, request: LLMRequest = request) -> dict[str, Any]:
            parsed, receipts = execute_cached(
                cache=cache,
                request=request,
                parser=lambda text: parse_question_conflict_map(
                    text, expected_questions=len(item["questions"])
                ),
                metadata={
                    "role": "query_aligned_answer_conflict",
                    "packet_key": item["packet_key"],
                    "model_id": item["victim_model_id"],
                    "claim_id": item["claim_id"],
                },
                contract_name="query-aligned answer-conflict contract",
                retries=decoding["contract_retries"],
            )
            output_identity = hashlib.sha256(
                canonical_json(
                    {
                        "output_schema_version": 1,
                        "packet_key": item["packet_key"],
                        "cache_key": receipts[-1]["cache_key"],
                    }
                ).encode()
            ).hexdigest()
            output = {
                "output_schema_version": 1,
                "contract_version": CONFLICT_MAP_CONTRACT_VERSION,
                "output_key": output_identity,
                "packet_key": item["packet_key"],
                "judgment": parsed,
                "receipts": receipts,
            }
            path = output_root / output_identity[:2] / f"{output_identity}.json"
            if path.exists():
                stored = json.loads(path.read_text(encoding="utf-8"))
                if (
                    stored.get("output_key") != output_identity
                    or stored.get("packet_key") != item["packet_key"]
                    or stored.get("judgment") != parsed
                ):
                    raise RuntimeError(f"Existing conflict-map output does not match: {path}")
                artifact_hit = True
            else:
                path, artifact_hit = store_immutable_output(
                    output_root, output_identity, output
                )
            return {
                "victim_model_id": item["victim_model_id"],
                "claim_id": item["claim_id"],
                "condition_id": item["condition_id"],
                "rag_task_key": item["rag_task_key"],
                "case_key": item["case_key"],
                "packet_key": item["packet_key"],
                "packet_path": packet_paths[item["packet_key"]],
                "output_key": output_identity,
                "output_path": str(path),
                "cache_key": receipts[-1]["cache_key"],
                "cache_hit": receipts[-1]["cache_hit"],
                "artifact_hit": artifact_hit,
                "receipts": receipts,
            }

        jobs.append((item["packet_key"], job))

    completed = {}
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_jobs = {executor.submit(function): identity for identity, function in jobs}
        for count, future in enumerate(concurrent.futures.as_completed(future_jobs), 1):
            identity = future_jobs[future]
            try:
                completed[identity] = future.result()
                print(f"conflict_map {count}/{len(jobs)} packet={identity} cached={completed[identity]['cache_hit']}")
            except Exception as exc:
                failure = {
                    "identity": identity,
                    "error_type": type(exc).__name__,
                    "error": repr(exc),
                    "traceback": traceback.format_exc(),
                }
                receipts = getattr(exc, "receipts", None)
                if receipts is not None:
                    failure["receipts"] = receipts
                failures.append(failure)
                print(f"conflict_map {count}/{len(jobs)} FAILED packet={identity}: {exc}")
            if count % 10 == 0 or count == len(jobs):
                ledger.update(
                    status="failed" if failures else "running",
                    phase="conflict_map",
                    event="query_aligned_conflict_map_progress",
                    counts={"expected": len(jobs), "completed": len(completed), "failed": len(failures)},
                )

    manifest_rows = []
    for item in prepared:
        shared = completed.get(item["packet_key"])
        if shared is None:
            continue
        manifest_rows.append(
            {
                **shared,
                "victim_model_id": item["victim_model_id"],
                "claim_id": item["claim_id"],
                "condition_id": item["condition_id"],
                "rag_task_key": item["rag_task_key"],
                "case_key": item["case_key"],
            }
        )
    manifest = {
        "manifest_schema_version": 1,
        **preparation,
        "prompt_version": template_version,
        "completed_outputs": len(completed),
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
    ledger.update(
        status="failed" if failures or len(completed) != len(jobs) else "complete",
        phase="complete" if not failures else "conflict_map",
        event="query_aligned_conflict_map_finished",
        counts={"expected": len(jobs), "completed": len(completed), "failed": len(failures)},
        artifacts={"private_manifest": str(manifest_path)},
    )
    print(json.dumps({**preparation, "completed": len(completed), "failed": len(failures)}, indent=2))
    if failures or len(completed) != len(jobs):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
