#!/usr/bin/env python3
"""Run the cached Stage 3 evidence-critic and claim-arbiter workflow."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import LLMCache, LLMRequest, canonical_json
from parametric_rag_defense.contracts import ContractError
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.providers import openai_compatible_complete
from parametric_rag_defense.stage2_packets import validate_visible_packet
from parametric_rag_defense.stage3_contracts import (
    STAGE3_CONTRACT_VERSION,
    parse_claim_arbiter,
    parse_evidence_critic,
)


Parser = Callable[[str], dict[str, Any]]


def prompt_version(path: Path, identifier: str) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode()).hexdigest()
    lock_path = path.with_suffix(path.suffix + ".sha256")
    if lock_path.exists():
        expected = lock_path.read_text(encoding="utf-8").strip().split()[0]
        if expected != digest:
            raise RuntimeError(
                f"Prompt digest mismatch for {path}: expected {expected}, observed {digest}"
            )
    return text, f"{identifier}+sha256:{digest}"


def render(template: str, replacements: dict[str, str]) -> str:
    result = template
    for marker, value in replacements.items():
        result = result.replace("{{" + marker + "}}", value)
    if "{{" in result or "}}" in result:
        raise ValueError("Unresolved placeholder remains in Stage 3 prompt")
    return result


def parsed_response(parser: Parser, response: dict[str, Any]) -> dict[str, Any]:
    try:
        response["parsed"] = parser(response["raw_text"])
        response["contract_ok"] = True
    except ContractError as exc:
        response["parsed"] = None
        response["contract_ok"] = False
        response["contract_error"] = str(exc)
    return response


def retry_request(request: LLMRequest, attempt: int, contract_name: str) -> LLMRequest:
    return LLMRequest(
        stage=request.stage,
        provider=request.provider,
        model=request.model,
        prompt_id=request.prompt_id,
        prompt_version=f"{request.prompt_version}+contract-retry:{attempt}",
        messages=[
            *request.messages,
            {
                "role": "user",
                "content": (
                    f"Format-repair attempt {attempt}: return the {contract_name} again as exactly "
                    "one JSON object satisfying every field, enum, and list limit."
                ),
            },
        ],
        parameters=request.parameters,
        response_format=request.response_format,
    )


def execute_cached(
    *,
    cache: LLMCache,
    request: LLMRequest,
    parser: Parser,
    metadata: dict[str, Any],
    contract_name: str,
    retries: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    active_request = request
    receipts: list[dict[str, Any]] = []
    for attempt in range(retries + 1):
        entry, cache_hit = cache.get_or_compute(
            active_request,
            lambda current=active_request: parsed_response(
                parser, openai_compatible_complete(current)
            ),
            metadata={**metadata, "contract_attempt": attempt},
        )
        try:
            current_parsed = parser(entry["response"]["raw_text"])
            current_contract_ok = True
            current_contract_error = None
        except ContractError as exc:
            current_parsed = None
            current_contract_ok = False
            current_contract_error = str(exc)
        receipts.append(
            {
                "attempt": attempt,
                "cache_key": active_request.key,
                "cache_hit": cache_hit,
                "stored_contract_ok": bool(entry["response"].get("contract_ok")),
                "contract_ok": current_contract_ok,
                "contract_error": current_contract_error,
                "structured_contract_version": STAGE3_CONTRACT_VERSION,
            }
        )
        if current_contract_ok:
            assert current_parsed is not None
            return current_parsed, receipts
        if attempt < retries:
            active_request = retry_request(request, attempt + 1, contract_name)
    raise ContractError(f"{contract_name} failed after {retries + 1} attempts")


def immutable_output(root: Path, value: dict[str, Any]) -> tuple[Path, bool]:
    output_key = value["output_key"]
    path = root / output_key[:2] / f"{output_key}.json"
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != serialized:
            raise RuntimeError(f"Refusing to overwrite conflicting Stage 3 output: {path}")
        return path, True
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{output_key}.", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path, False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1-config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--workflow-config", type=Path, default=Path("configs/stage234_workflow.json")
    )
    parser.add_argument(
        "--stage2-root", type=Path, default=Path("artifacts/runs/stage2/stage2_signal_v1")
    )
    parser.add_argument("--experiment-id", default="stage3_claim_arbiter_v1")
    parser.add_argument("--conditions", help="Comma-separated override of configured pilot conditions")
    parser.add_argument("--claims", help="Optional comma-separated smoke-test claim IDs")
    parser.add_argument("--arbiter-models", help="Comma-separated arbiter-model ID subset")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--contract-retries",
        type=int,
        help="Override the configured format-repair retry limit without changing successful calls",
    )
    args = parser.parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if args.contract_retries is not None and args.contract_retries < 0:
        raise SystemExit("--contract-retries cannot be negative")

    stage1 = json.loads(args.stage1_config.read_text(encoding="utf-8"))
    workflow = json.loads(args.workflow_config.read_text(encoding="utf-8"))
    stage3 = workflow["stage3"]
    load_dotenv(args.stage1_config.resolve().parent.parent / ".env")
    models = {model["id"]: model for model in stage1["models"] if model.get("enabled")}
    critic_model = models[stage3["critic_model"]]
    arbiter_ids = list(stage3["arbiter_candidates"])
    if args.arbiter_models:
        requested_arbiters = set(args.arbiter_models.split(","))
        arbiter_ids = [model_id for model_id in arbiter_ids if model_id in requested_arbiters]
        missing = requested_arbiters - set(arbiter_ids)
        if missing:
            raise SystemExit(f"Unknown or unconfigured arbiter models: {sorted(missing)}")
    arbiter_models = [models[model_id] for model_id in arbiter_ids]
    conditions = set(args.conditions.split(",")) if args.conditions else set(
        stage3["initial_pilot_conditions"]
    )
    selected_claims = set(int(value) for value in args.claims.split(",")) if args.claims else None

    index = json.loads((args.stage2_root / "private_index.json").read_text(encoding="utf-8"))
    rows = [
        row
        for row in index["rows"]
        if row["condition_id"] in conditions
        and (selected_claims is None or int(row["claim_id"]) in selected_claims)
    ]
    rows.sort(key=lambda row: (row["claim_id"], row["victim_model_id"], row["condition_id"]))
    if not rows:
        raise SystemExit("No Stage 2 packets match the requested pilot conditions/claims")

    critic_path = Path(stage3["prompts"]["critic"])
    arbiter_path = Path(stage3["prompts"]["arbiter"])
    critic_template, critic_version = prompt_version(critic_path, "stage3_evidence_critic_v1")
    arbiter_template, arbiter_version = prompt_version(arbiter_path, "stage3_claim_arbiter_v1")
    decoding = stage3["decoding"]
    retries = (
        args.contract_retries
        if args.contract_retries is not None
        else int(decoding["contract_retries"])
    )
    cache = LLMCache(Path(stage1["cache_root"]).resolve())
    run_root = Path("artifacts/runs/stage3") / args.experiment_id
    output_root = run_root / "outputs"
    ledger = ExperimentLedger(
        Path("artifacts/runs/progress"),
        args.experiment_id,
        description="Claim-level evidence-critic and LLM-arbiter workflow",
    )
    ledger.update(
        status="running",
        phase="evidence_critic",
        event="stage3_pilot_started",
        counts={"packets": len(rows), "critic_completed": 0, "arbiter_completed": 0, "failed": 0},
        details={"conditions": sorted(conditions), "arbiter_models": arbiter_ids},
    )

    loaded_packets: dict[str, dict[str, Any]] = {}
    for row in rows:
        packet = json.loads(Path(row["packet_path"]).read_text(encoding="utf-8"))
        if packet["packet_key"] != row["packet_key"]:
            raise ValueError(f"Packet/index mismatch: {row['packet_path']}")
        validate_visible_packet(packet["visible"])
        loaded_packets[row["packet_key"]] = packet

    critic_results: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []

    def critic_job(row: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        packet = loaded_packets[row["packet_key"]]
        visible = packet["visible"]
        critic_record = {
            "claim": visible["claim"],
            "claim_date": visible["claim_date"],
            "retrieval_assessment": visible["retrieval_assessment"],
        }
        prompt = render(
            critic_template,
            {
                "RETRIEVAL_RECORD": json.dumps(
                    critic_record, ensure_ascii=False, sort_keys=True, indent=2
                )
            },
        )
        request = LLMRequest(
            stage="stage3_evidence_critic",
            provider=critic_model["provider"],
            model=critic_model["model"],
            prompt_id="stage3_evidence_critic",
            prompt_version=critic_version,
            messages=[{"role": "user", "content": prompt}],
            parameters={
                "temperature": decoding["temperature"],
                "top_p": decoding["top_p"],
                "max_tokens": decoding["critic_max_tokens"],
                "seed": decoding["seed"],
                **critic_model.get("request_parameters", {}),
            },
            response_format={"type": "json_object"},
        )
        return execute_cached(
            cache=cache,
            request=request,
            parser=parse_evidence_critic,
            metadata={
                "role": "stage3_evidence_critic",
                "packet_key": row["packet_key"],
                "model_id": critic_model["id"],
            },
            contract_name="evidence critic contract",
            retries=retries,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_rows = {executor.submit(critic_job, row): row for row in rows}
        for completed, future in enumerate(concurrent.futures.as_completed(future_rows), 1):
            row = future_rows[future]
            try:
                parsed, receipts = future.result()
                critic_results[row["packet_key"]] = {"judgment": parsed, "receipts": receipts}
                print(
                    f"critic {completed}/{len(rows)} claim={row['claim_id']} "
                    f"victim={row['victim_model_id']} condition={row['condition_id']} "
                    f"cached={receipts[-1]['cache_hit']}"
                )
            except Exception as exc:
                failures.append(
                    {"phase": "critic", **row, "error": repr(exc), "traceback": traceback.format_exc()}
                )
                print(f"critic {completed}/{len(rows)} FAILED packet={row['packet_key'][:12]}: {exc}")
            if completed % 10 == 0 or completed == len(rows):
                ledger.update(
                    status="running" if not failures else "failed",
                    phase="evidence_critic",
                    event="critic_progress",
                    counts={
                        "packets": len(rows),
                        "critic_completed": len(critic_results),
                        "arbiter_completed": 0,
                        "failed": len(failures),
                    },
                )

    output_rows: list[dict[str, Any]] = []

    def arbiter_job(row: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
        packet = loaded_packets[row["packet_key"]]
        visible = packet["visible"]
        retrieval_block = {
            "assessment_role": "retrieval",
            "content": visible["retrieval_assessment"],
        }
        memory_block = {
            "assessment_role": "memory_only",
            "content": visible["memory_only_assessments"],
        }
        if int(row["packet_key"][0], 16) % 2:
            first, second, order = memory_block, retrieval_block, "memory_then_retrieval"
        else:
            first, second, order = retrieval_block, memory_block, "retrieval_then_memory"
        prompt = render(
            arbiter_template,
            {
                "CLAIM_RECORD": json.dumps(
                    {"claim": visible["claim"], "claim_date": visible["claim_date"]},
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                ),
                "FIRST_BLOCK": json.dumps(first, ensure_ascii=False, sort_keys=True, indent=2),
                "SECOND_BLOCK": json.dumps(second, ensure_ascii=False, sort_keys=True, indent=2),
                "CRITIC_RECORD": json.dumps(
                    critic_results[row["packet_key"]]["judgment"],
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                ),
            },
        )
        request = LLMRequest(
            stage="stage3_claim_arbiter",
            provider=model["provider"],
            model=model["model"],
            prompt_id="stage3_claim_arbiter",
            prompt_version=arbiter_version,
            messages=[{"role": "user", "content": prompt}],
            parameters={
                "temperature": decoding["temperature"],
                "top_p": decoding["top_p"],
                "max_tokens": decoding["arbiter_max_tokens"],
                "seed": decoding["seed"],
                **model.get("request_parameters", {}),
            },
            response_format={"type": "json_object"},
        )
        judgment, receipts = execute_cached(
            cache=cache,
            request=request,
            parser=parse_claim_arbiter,
            metadata={
                "role": "stage3_claim_arbiter",
                "packet_key": row["packet_key"],
                "model_id": model["id"],
                "presentation_order": order,
            },
            contract_name="claim arbiter contract",
            retries=retries,
        )
        output_key = hashlib.sha256(
            canonical_json(
                {
                    "packet_key": row["packet_key"],
                    "critic_cache_key": critic_results[row["packet_key"]]["receipts"][-1]["cache_key"],
                    "arbiter_cache_key": receipts[-1]["cache_key"],
                    "structured_contract_version": STAGE3_CONTRACT_VERSION,
                }
            ).encode()
        ).hexdigest()
        output = {
            "stage3_output_schema_version": 1,
            "structured_contract_version": STAGE3_CONTRACT_VERSION,
            "output_key": output_key,
            "packet_key": row["packet_key"],
            "critic": {
                "model_id": critic_model["id"],
                "cache_key": critic_results[row["packet_key"]]["receipts"][-1]["cache_key"],
                "judgment": critic_results[row["packet_key"]]["judgment"],
            },
            "arbiter": {
                "model_id": model["id"],
                "cache_key": receipts[-1]["cache_key"],
                "presentation_order": order,
                "judgment": judgment,
            },
        }
        path, cached = immutable_output(output_root, output)
        return {
            "output_key": output_key,
            "output_path": str(path),
            "cached_output": cached,
            "arbiter_cache_hit": receipts[-1]["cache_hit"],
            "arbiter_model_id": model["id"],
            "route": judgment["route"],
            "final_verdict": judgment["final_verdict"],
        }

    arbiter_jobs = [
        (row, model)
        for row in rows
        if row["packet_key"] in critic_results
        for model in arbiter_models
    ]
    ledger.update(
        status="running" if not failures else "failed",
        phase="claim_arbiter",
        event="arbiter_started",
        counts={
            "packets": len(rows),
            "critic_completed": len(critic_results),
            "arbiter_expected": len(arbiter_jobs),
            "arbiter_completed": 0,
            "failed": len(failures),
        },
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_jobs = {
            executor.submit(arbiter_job, row, model): (row, model) for row, model in arbiter_jobs
        }
        for completed, future in enumerate(concurrent.futures.as_completed(future_jobs), 1):
            row, model = future_jobs[future]
            try:
                result = future.result()
                output_rows.append({**row, **result})
                print(
                    f"arbiter {completed}/{len(arbiter_jobs)} model={model['id']} "
                    f"claim={row['claim_id']} condition={row['condition_id']} "
                    f"route={result['route']} verdict={result['final_verdict']} "
                    f"cached={result['arbiter_cache_hit']}"
                )
            except Exception as exc:
                failures.append(
                    {
                        "phase": "arbiter",
                        **row,
                        "arbiter_model_id": model["id"],
                        "error": repr(exc),
                        "traceback": traceback.format_exc(),
                    }
                )
                print(
                    f"arbiter {completed}/{len(arbiter_jobs)} FAILED "
                    f"model={model['id']} packet={row['packet_key'][:12]}: {exc}"
                )
            if completed % 10 == 0 or completed == len(arbiter_jobs):
                ledger.update(
                    status="running" if not failures else "failed",
                    phase="claim_arbiter",
                    event="arbiter_progress",
                    counts={
                        "packets": len(rows),
                        "critic_completed": len(critic_results),
                        "arbiter_expected": len(arbiter_jobs),
                        "arbiter_completed": len(output_rows),
                        "failed": len(failures),
                    },
                )

    output_rows.sort(
        key=lambda row: (
            row["claim_id"], row["victim_model_id"], row["condition_id"], row["arbiter_model_id"]
        )
    )
    manifest_path = run_root / "private_manifest.json"
    atomic_json(
        manifest_path,
        {
            "warning": "PRIVATE ROUTING MANIFEST: condition/model metadata must not enter prompts",
            "experiment_id": args.experiment_id,
            "conditions": sorted(conditions),
            "critic_model_id": critic_model["id"],
            "arbiter_model_ids": arbiter_ids,
            "requested_packets": len(rows),
            "critic_completed": len(critic_results),
            "arbiter_expected": len(arbiter_jobs),
            "outputs": output_rows,
            "failures": failures,
        },
    )
    final_status = "complete" if not failures and len(output_rows) == len(arbiter_jobs) else "failed"
    ledger.update(
        status=final_status,
        phase="claim_arbiter",
        event="stage3_pilot_completed" if final_status == "complete" else "stage3_pilot_failed",
        counts={
            "packets": len(rows),
            "critic_completed": len(critic_results),
            "arbiter_expected": len(arbiter_jobs),
            "arbiter_completed": len(output_rows),
            "failed": len(failures),
        },
        artifacts={"manifest": str(manifest_path)},
    )
    print(
        f"wrote {manifest_path}; packets={len(rows)} critic={len(critic_results)} "
        f"arbiter={len(output_rows)}/{len(arbiter_jobs)} failures={len(failures)}"
    )
    if final_status != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
