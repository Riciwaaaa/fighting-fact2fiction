#!/usr/bin/env python3
"""Collect claim-only plans and endpoint-hidden passage maps on cached disagreements."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from build_stage2_packets import internal_lookup
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import LLMCache, LLMRequest, canonical_json
from parametric_rag_defense.contracts import ContractError
from parametric_rag_defense.evidence_signals import (
    EVIDENCE_MAP_CONTRACT_VERSION,
    build_evidence_packet,
    parse_evidence_map_text,
)
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.labels import deterministic_majority
from parametric_rag_defense.matrix import all_attack_conditions
from parametric_rag_defense.neutral_firewall import (
    NEUTRAL_PLAN_CONTRACT_VERSION,
    parse_neutral_plan_text,
)
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.providers import openai_compatible_complete
from parametric_rag_defense.workflow_runtime import (
    execute_cached,
    prompt_version,
    render,
    store_immutable_output,
)

DEFAULT_CONDITIONS = (
    "clean",
    "fact2fiction_p0.001",
    "fact2fiction_p0.0025",
    "fact2fiction_p0.005",
)


def evidence_retry_request(
    request: LLMRequest,
    *,
    attempt: int,
    contract_error: str,
    expected_passage_ids: set[str],
) -> LLMRequest:
    feedback = (
        f"Evidence-map format repair {attempt}. The previous JSON failed validation because: "
        f"{contract_error} Include every expected passage exactly once in passage_assessments: "
        f"{', '.join(sorted(expected_passage_ids))}. Content clusters may omit passages that do "
        "not share a substantive factual assertion, but a passage may appear in at most one "
        "cluster. Return the entire JSON object again with exactly the requested fields and enums."
    )
    return LLMRequest(
        stage=request.stage,
        provider=request.provider,
        model=request.model,
        prompt_id=request.prompt_id,
        prompt_version=f"{request.prompt_version}+evidence-contract-retry:{attempt}",
        messages=[*request.messages, {"role": "user", "content": feedback}],
        parameters=request.parameters,
        response_format=request.response_format,
    )


def execute_evidence_cached(
    *,
    cache: LLMCache,
    request: LLMRequest,
    expected_passage_ids: set[str],
    metadata: dict[str, Any],
    retries: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute an evidence map with contract-specific, semantics-preserving feedback."""

    active_request = request
    receipts: list[dict[str, Any]] = []
    for attempt in range(retries + 1):
        parser = lambda text: parse_evidence_map_text(
            text, expected_passage_ids=expected_passage_ids
        )

        def compute(current: LLMRequest = active_request) -> dict[str, Any]:
            response = openai_compatible_complete(current)
            try:
                response["parsed"] = parser(response["raw_text"])
                response["contract_ok"] = True
            except ContractError as exc:
                response["parsed"] = None
                response["contract_ok"] = False
                response["contract_error"] = str(exc)
            return response

        entry, cache_hit = cache.get_or_compute(
            active_request,
            compute,
            metadata={**metadata, "contract_attempt": attempt},
        )
        try:
            parsed = parser(entry["response"]["raw_text"])
            contract_error = None
        except ContractError as exc:
            parsed = None
            contract_error = str(exc)
        receipts.append(
            {
                "attempt": attempt,
                "cache_key": active_request.key,
                "cache_hit": cache_hit,
                "contract_ok": parsed is not None,
                "contract_error": contract_error,
            }
        )
        if parsed is not None:
            return parsed, receipts
        if attempt < retries:
            active_request = evidence_retry_request(
                request,
                attempt=attempt + 1,
                contract_error=contract_error or "unknown contract error",
                expected_passage_ids=expected_passage_ids,
            )
    error = ContractError(
        f"passage-complete evidence-map contract failed after {retries + 1} attempts"
    )
    error.receipts = receipts
    raise error


def execute_jobs(
    jobs: list[tuple[Any, Callable[[], dict[str, Any]]]],
    *,
    workers: int,
    phase: str,
    failures: list[dict[str, Any]],
    ledger: ExperimentLedger,
) -> dict[Any, dict[str, Any]]:
    results: dict[Any, dict[str, Any]] = {}
    ledger.update(
        status="running" if not failures else "failed",
        phase=phase,
        event=f"{phase}_started",
        counts={"expected": len(jobs), "completed": 0, "failed": len(failures)},
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_jobs = {executor.submit(function): identity for identity, function in jobs}
        for completed, future in enumerate(concurrent.futures.as_completed(future_jobs), 1):
            identity = future_jobs[future]
            try:
                results[identity] = future.result()
                print(
                    f"{phase} {completed}/{len(jobs)} identity={identity} "
                    f"cached={results[identity].get('cache_hit')}"
                )
            except Exception as exc:
                failure = {
                    "phase": phase,
                    "identity": repr(identity),
                    "error_type": type(exc).__name__,
                    "error": repr(exc),
                    "traceback": traceback.format_exc(),
                }
                receipts = getattr(exc, "receipts", None)
                if receipts is not None:
                    failure["receipts"] = receipts
                failures.append(failure)
                print(f"{phase} {completed}/{len(jobs)} FAILED identity={identity}: {exc}")
            if completed % 10 == 0 or completed == len(jobs):
                ledger.update(
                    status="running" if not failures else "failed",
                    phase=phase,
                    event=f"{phase}_progress",
                    counts={
                        "expected": len(jobs),
                        "completed": len(results),
                        "failed": len(failures),
                    },
                )
    return results


def case_key(model_id: str, claim: str, claim_date: str) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "case_schema_version": 1,
                "model_id": model_id,
                "claim": claim,
                "claim_date": claim_date,
            }
        ).encode()
    ).hexdigest()


def disagreement_scope(
    *,
    config: dict[str, Any],
    requested_models: set[str],
    requested_conditions: set[str],
    selected_claims: set[int] | None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    dataset = json.loads(Path(config["dataset"]["source"]).read_text(encoding="utf-8"))
    split = json.loads(Path(config["dataset"]["split_manifest"]).read_text(encoding="utf-8"))
    active_split = config["dataset"].get("active_split", "development")
    development_claims = set(int(value) for value in split[active_split]["claim_ids"])
    if selected_claims is not None:
        development_claims &= selected_claims
    samples, _ = internal_lookup(
        config,
        Path(config["run_root"]) / active_split / "internal_endpoint",
        Path(config["cache_root"]),
    )
    memory_predictions = {
        model_id: {
            int(claim_id): deterministic_majority(sample["verdict"] for sample in judgments)
            for claim_id, judgments in claim_samples.items()
        }
        for model_id, claim_samples in samples.items()
    }
    namespace = config["rag_pipeline"]["artifact_namespace"]
    endpoint_root = (
        Path(config["run_root"]) / active_split / "rag" / namespace / "endpoints"
    )
    rows: list[dict[str, Any]] = []
    cases: dict[str, dict[str, Any]] = {}
    seen_identities: set[tuple[str, int, str]] = set()
    for endpoint_path in sorted(endpoint_root.glob("*/*.json")):
        endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
        task = endpoint["task"]
        model_id = str(task["model_id"])
        claim_id = int(task["claim_id"])
        condition_id = str(task["condition"]["id"])
        if (
            model_id not in requested_models
            or claim_id not in development_claims
            or condition_id not in requested_conditions
        ):
            continue
        identity = (model_id, claim_id, condition_id)
        if identity in seen_identities:
            raise ValueError(f"Duplicate endpoint identity: {identity}")
        seen_identities.add(identity)
        memory_prediction = memory_predictions[model_id][claim_id]
        retrieval_prediction = endpoint["judgment"]["verdict"]
        if retrieval_prediction == memory_prediction:
            continue
        record = dataset[claim_id]
        claim = str(record["claim"]).strip()
        claim_date = str(record.get("claim_date") or "unknown")
        identity_key = case_key(model_id, claim, claim_date)
        case = {
            "case_key": identity_key,
            "model_id": model_id,
            "claim": claim,
            "claim_date": claim_date,
        }
        existing = cases.setdefault(identity_key, case)
        if existing != case:
            raise ValueError(f"Case-key collision: {identity_key}")
        rows.append(
            {
                "claim_id": claim_id,
                "victim_model_id": model_id,
                "condition_id": condition_id,
                "rag_task_key": endpoint["task_key"],
                "endpoint_path": str(endpoint_path),
                "retrieval_prediction": retrieval_prediction,
                "memory_prediction": memory_prediction,
                "case_key": identity_key,
            }
        )
    rows.sort(key=lambda row: (row["claim_id"], row["victim_model_id"], row["condition_id"]))
    return rows, cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument("--experiment-id", default="evidence_signal_v1")
    parser.add_argument("--conditions", default=",".join(DEFAULT_CONDITIONS))
    parser.add_argument("--models", help="Optional comma-separated model-ID subset")
    parser.add_argument("--claims", help="Optional comma-separated claim-ID subset")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--contract-retries", type=int, default=2)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1 or args.contract_retries < 0:
        raise SystemExit("workers must be positive and contract retries nonnegative")

    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    load_dotenv(config_path.parent.parent / ".env")
    models = {
        model["id"]: model
        for model in config["models"]
        if model.get("enabled") and "rag_victim" in model["roles"] and "arbiter" in model["roles"]
    }
    requested_models = set(args.models.split(",")) if args.models else set(models)
    missing_models = requested_models - set(models)
    if missing_models:
        raise SystemExit(f"Unknown same-model configurations: {sorted(missing_models)}")
    requested_conditions = {value for value in args.conditions.split(",") if value}
    allowed_conditions = {
        condition["id"]
        for condition in all_attack_conditions(config)
    }
    if not requested_conditions or requested_conditions - allowed_conditions:
        raise SystemExit(
            f"Conditions must be a non-empty subset of {sorted(allowed_conditions)}"
        )
    selected_claims = (
        {int(value) for value in args.claims.split(",")} if args.claims else None
    )

    rows, cases = disagreement_scope(
        config=config,
        requested_models=requested_models,
        requested_conditions=requested_conditions,
        selected_claims=selected_claims,
    )
    if not rows:
        raise SystemExit("No endpoint disagreements match the requested scope")
    condition_counts = Counter(row["condition_id"] for row in rows)
    model_condition_counts = Counter(
        (row["victim_model_id"], row["condition_id"]) for row in rows
    )
    preparation = {
        "experiment_id": args.experiment_id,
        "conditions": sorted(requested_conditions),
        "models": sorted(requested_models),
        "disagreement_rows": len(rows),
        "unique_model_claim_cases": len(cases),
        "condition_counts": dict(sorted(condition_counts.items())),
        "model_condition_counts": {
            f"{model_id}:{condition_id}": count
            for (model_id, condition_id), count in sorted(model_condition_counts.items())
        },
        "maximum_new_calls": len(cases) + len(rows),
    }
    if args.prepare_only:
        print(json.dumps(preparation, indent=2, sort_keys=True))
        return

    study_parent = Path(config["run_root"]).parent
    run_root = study_parent / "evidence_signal" / args.experiment_id
    packet_root = run_root / "packets"
    output_root = run_root / "outputs"
    cache = LLMCache(Path(config["cache_root"]).resolve())
    ledger = ExperimentLedger(
        Path(config.get("progress_root", "artifacts/runs/progress")),
        args.experiment_id,
        description="Claim-only planning and endpoint-hidden passage signal mapping",
    )
    ledger.update(
        status="running",
        phase="preparation",
        event="evidence_signal_started",
        counts={
            "disagreement_rows": len(rows),
            "unique_cases": len(cases),
            "completed": 0,
            "failed": 0,
        },
        details={"conditions": sorted(requested_conditions), "models": sorted(requested_models)},
    )
    plan_template, plan_version = prompt_version(
        Path("prompts/neutral_claim_plan_v1.md"), "neutral_claim_plan_v1"
    )
    evidence_template, evidence_version = prompt_version(
        Path("prompts/evidence_passage_map_v1.md"), "evidence_passage_map_v1"
    )
    failures: list[dict[str, Any]] = []

    plan_jobs = []
    for identity, case in sorted(cases.items()):

        def plan_job(case: dict[str, Any] = case) -> dict[str, Any]:
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
                    "role": "evidence_signal_claim_plan",
                    "case_key": case["case_key"],
                    "model_id": case["model_id"],
                },
                contract_name="neutral claim-plan contract",
                retries=args.contract_retries,
            )
            return {
                "judgment": judgment,
                "cache_key": receipts[-1]["cache_key"],
                "cache_hit": receipts[-1]["cache_hit"],
                "receipts": receipts,
            }

        plan_jobs.append((identity, plan_job))
    plans = execute_jobs(
        plan_jobs,
        workers=args.workers,
        phase="claim_plan",
        failures=failures,
        ledger=ledger,
    )

    prepared: list[dict[str, Any]] = []
    packet_cache_hits = 0
    for row in rows:
        if row["case_key"] not in plans:
            continue
        endpoint = json.loads(Path(row["endpoint_path"]).read_text(encoding="utf-8"))
        case = cases[row["case_key"]]
        plan = plans[row["case_key"]]
        packet = build_evidence_packet(
            claim=case["claim"],
            claim_date=case["claim_date"],
            rag_task_key=row["rag_task_key"],
            rag_judgment=endpoint["judgment"],
            neutral_plan=plan["judgment"],
            neutral_plan_cache_key=plan["cache_key"],
            same_model_id=row["victim_model_id"],
        )
        packet_path, cached_packet = store_immutable_output(
            packet_root, packet["packet_key"], packet
        )
        packet_cache_hits += int(cached_packet)
        prepared.append(
            {
                **row,
                "packet": packet,
                "packet_path": str(packet_path),
                "plan_cache_key": plan["cache_key"],
            }
        )

    evidence_jobs = []
    for item in prepared:

        def evidence_job(item: dict[str, Any] = item) -> dict[str, Any]:
            model = models[item["victim_model_id"]]
            packet = item["packet"]
            prompt = render(
                evidence_template,
                {
                    "EVIDENCE_PACKET": json.dumps(
                        packet["visible"], ensure_ascii=False, sort_keys=True, indent=2
                    )
                },
            )
            expected_ids = {
                passage["passage_id"] for passage in packet["visible"]["passages"]
            }
            request = LLMRequest(
                stage="evidence_signal_passage_map_v1",
                provider=model["provider"],
                model=model["model"],
                prompt_id="evidence_passage_map",
                prompt_version=evidence_version,
                messages=[{"role": "user", "content": prompt}],
                parameters={
                    "temperature": 0.1,
                    "top_p": 0.7,
                    "max_tokens": 6000,
                    "seed": 409,
                    **model.get("request_parameters", {}),
                },
                response_format={"type": "json_object"},
            )
            judgment, receipts = execute_evidence_cached(
                cache=cache,
                request=request,
                expected_passage_ids=expected_ids,
                metadata={
                    "role": "evidence_signal_passage_map",
                    "packet_key": packet["packet_key"],
                    "model_id": item["victim_model_id"],
                },
                retries=args.contract_retries,
            )
            output_key = hashlib.sha256(
                canonical_json(
                    {
                        "packet_key": packet["packet_key"],
                        "evidence_cache_key": receipts[-1]["cache_key"],
                        "contract_version": EVIDENCE_MAP_CONTRACT_VERSION,
                    }
                ).encode()
            ).hexdigest()
            output = {
                "output_schema_version": 1,
                "contract_version": EVIDENCE_MAP_CONTRACT_VERSION,
                "output_key": output_key,
                "packet_key": packet["packet_key"],
                "plan_cache_key": item["plan_cache_key"],
                "evidence_cache_key": receipts[-1]["cache_key"],
                "judgment": judgment,
            }
            output_path, cached_output = store_immutable_output(
                output_root, output_key, output
            )
            return {
                "output_key": output_key,
                "output_path": str(output_path),
                "cache_key": receipts[-1]["cache_key"],
                "cache_hit": receipts[-1]["cache_hit"],
                "cached_output": cached_output,
                "receipts": receipts,
            }

        evidence_jobs.append((item["rag_task_key"], evidence_job))
    evidence_results = execute_jobs(
        evidence_jobs,
        workers=args.workers,
        phase="passage_map",
        failures=failures,
        ledger=ledger,
    )

    manifest_rows = []
    for item in prepared:
        result = evidence_results.get(item["rag_task_key"])
        if result is None:
            continue
        manifest_rows.append(
            {
                **{key: value for key, value in item.items() if key != "packet"},
                **result,
            }
        )
    manifest_rows.sort(
        key=lambda row: (row["claim_id"], row["victim_model_id"], row["condition_id"])
    )
    manifest = {
        "warning": "PRIVATE METADATA: never serialize condition, endpoints, or model IDs into prompts",
        "manifest_schema_version": 1,
        **preparation,
        "neutral_plan_contract_version": NEUTRAL_PLAN_CONTRACT_VERSION,
        "evidence_map_contract_version": EVIDENCE_MAP_CONTRACT_VERSION,
        "packet_cache_hits": packet_cache_hits,
        "completed_plans": len(plans),
        "completed_outputs": len(manifest_rows),
        "rows": manifest_rows,
        "failures": failures,
    }
    manifest_path = run_root / "private_manifest.json"
    atomic_json(manifest_path, manifest)
    status = (
        "complete"
        if len(plans) == len(cases) and len(manifest_rows) == len(rows) and not failures
        else "failed"
    )
    ledger.update(
        status=status,
        phase="passage_map",
        event="evidence_signal_completed" if status == "complete" else "evidence_signal_failed",
        counts={
            "disagreement_rows": len(rows),
            "unique_cases": len(cases),
            "completed_plans": len(plans),
            "completed_outputs": len(manifest_rows),
            "failed": len(failures),
        },
        artifacts={"manifest": str(manifest_path)},
    )
    print(
        json.dumps(
            {
                "status": status,
                "plans": len(plans),
                "outputs": len(manifest_rows),
                "failures": len(failures),
            },
            indent=2,
        )
    )
    if status != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
