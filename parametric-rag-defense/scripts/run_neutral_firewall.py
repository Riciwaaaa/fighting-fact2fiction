#!/usr/bin/env python3
"""Run neutral pre-endpoint planning plus rationale-firewalled same-model selection."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from parametric_rag_defense.aligned_workflow import (
    candidate_prediction,
    parse_aligned_final_text,
)
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import LLMCache, LLMRequest, canonical_json
from parametric_rag_defense.contracts import parse_internal_judgment
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.neutral_firewall import (
    FIREWALLED_SELECTOR_CONTRACT_VERSION,
    NEUTRAL_PLAN_CONTRACT_VERSION,
    endpoint_prediction,
    parse_neutral_plan_text,
)
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.workflow_runtime import (
    execute_cached,
    prompt_version,
    render,
    store_immutable_output,
)

VARIANTS = ("neutral_countercheck", "direct_deliberation")
DIRECT_PERSPECTIVES = (
    (
        "neutral",
        "Give a balanced independent assessment of the claim and identify the decisive known facts.",
        97,
    ),
    (
        "premise_skeptic",
        "Actively test the claim for false premises, reversed causality, and plausible counterfacts.",
        101,
    ),
    (
        "temporal_entity_binding",
        "Focus on exact entities, dates, quantities, negation, and whether recalled facts match the claim's scope.",
        103,
    ),
)


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
                    "case_key": (
                        identity[0]
                        if isinstance(identity, tuple)
                        and identity
                        and isinstance(identity[0], str)
                        and len(identity[0]) == 64
                        else None
                    ),
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage1-config", type=Path, default=Path("configs/stage1_crossed_defense.json")
    )
    parser.add_argument(
        "--router-root",
        type=Path,
        default=Path("artifacts/runs/stage3/stage3_crossed_defense_v2"),
    )
    parser.add_argument("--experiment-id", default="stage5_neutral_firewall_v1")
    parser.add_argument(
        "--conditions",
        default=(
            "clean,cross_glm52_p001,cross_llama31_70b_p001,"
            "cross_qwen35_35b_a3b_p001"
        ),
    )
    parser.add_argument("--variants", default=",".join(VARIANTS))
    parser.add_argument("--models", help="Optional comma-separated model-ID subset")
    parser.add_argument("--claims", help="Optional comma-separated claim-ID subset")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--contract-retries", type=int, default=2)
    parser.add_argument(
        "--fail-closed-case-keys",
        help=(
            "Optional comma-separated, predeclared case keys whose exhausted structured-output "
            "contracts resolve to the memory endpoint. Transport and other errors remain fatal."
        ),
    )
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1 or args.contract_retries < 0:
        raise SystemExit("workers must be positive and contract retries nonnegative")

    requested_variants = tuple(args.variants.split(","))
    fail_closed_case_keys = {
        value.strip()
        for value in (args.fail_closed_case_keys or "").split(",")
        if value.strip()
    }
    if any(len(value) != 64 for value in fail_closed_case_keys):
        raise SystemExit("Every fail-closed case key must be a 64-character SHA-256 digest")
    unknown_variants = set(requested_variants) - set(VARIANTS)
    if unknown_variants or not requested_variants:
        raise SystemExit(f"Unknown or empty variants: {sorted(unknown_variants)}")
    config_path = args.stage1_config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    load_dotenv(config_path.parent.parent / ".env")
    model_configs = {
        model["id"]: model
        for model in config["models"]
        if model.get("enabled") and "arbiter" in model["roles"]
    }
    requested_models = set(args.models.split(",")) if args.models else set(model_configs)
    missing_models = requested_models - set(model_configs)
    if missing_models:
        raise SystemExit(f"Unknown same-model configurations: {sorted(missing_models)}")
    requested_conditions = set(args.conditions.split(","))
    selected_claims = set(map(int, args.claims.split(","))) if args.claims else None

    router_manifest = json.loads(
        (args.router_root / "private_manifest.json").read_text(encoding="utf-8")
    )
    if router_manifest["dry_run"] or router_manifest["failures"]:
        raise ValueError("Router manifest is dry-run or contains failures")
    rows: list[dict[str, Any]] = []
    cases: dict[str, dict[str, Any]] = {}
    selector_inputs: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    for descriptor in router_manifest["outputs"]:
        if (
            descriptor["variant"] != "endpoint_only"
            or descriptor["victim_model_id"] not in requested_models
            or descriptor["condition_id"] not in requested_conditions
            or (
                selected_claims is not None
                and int(descriptor["claim_id"]) not in selected_claims
            )
        ):
            continue
        packet = json.loads(Path(descriptor["aligned_packet_path"]).read_text(encoding="utf-8"))
        visible = packet["visible"]
        rag = visible["retrieval_assessment"]["verdict"]
        memory = candidate_prediction(visible["memory_only_assessment"])
        if rag == memory:
            continue
        model_id = descriptor["victim_model_id"]
        identity = case_key(model_id, visible["claim"], visible["claim_date"])
        current_case = {
            "case_key": identity,
            "model_id": model_id,
            "claim": visible["claim"],
            "claim_date": visible["claim_date"],
        }
        existing_case = cases.setdefault(identity, current_case)
        if existing_case != current_case:
            raise ValueError(f"case-key collision: {identity}")
        selector_identity = (identity, rag, memory)
        selector_input = {
            "selector_identity": selector_identity,
            "case_key": identity,
            "model_id": model_id,
            "claim": visible["claim"],
            "claim_date": visible["claim_date"],
            "endpoint_labels": {"retrieval": rag, "memory": memory},
        }
        existing_selector = selector_inputs.setdefault(selector_identity, selector_input)
        if existing_selector != selector_input:
            raise ValueError(f"selector identity collision: {selector_identity}")
        rows.append(
            {
                "claim_id": int(descriptor["claim_id"]),
                "victim_model_id": model_id,
                "condition_id": descriptor["condition_id"],
                "aligned_packet_key": packet["packet_key"],
                "aligned_packet_path": descriptor["aligned_packet_path"],
                "case_key": identity,
                "selector_identity": selector_identity,
            }
        )
    rows.sort(key=lambda row: (row["claim_id"], row["victim_model_id"], row["condition_id"]))
    if not rows:
        raise SystemExit("No endpoint disagreements match the requested scope")
    expected_output_rows = len(rows) * len(requested_variants)
    expected_calls = {
        "neutral_countercheck": 3 * len(cases) + len(selector_inputs),
        "direct_deliberation": 3 * len(cases) + len(selector_inputs),
    }
    preparation = {
        "source_router_experiment": router_manifest["experiment_id"],
        "disagreement_rows": len(rows),
        "unique_model_claim_cases": len(cases),
        "unique_endpoint_label_inputs": len(selector_inputs),
        "variants": list(requested_variants),
        "expected_output_rows": expected_output_rows,
        "maximum_new_calls_by_variant": {
            variant: expected_calls[variant] for variant in requested_variants
        },
        "maximum_new_calls_total": sum(expected_calls[variant] for variant in requested_variants),
    }
    if args.prepare_only:
        print(json.dumps(preparation, indent=2, sort_keys=True))
        return

    plan_template, plan_version = prompt_version(
        Path("prompts/neutral_claim_plan_v1.md"), "neutral_claim_plan_v1"
    )
    support_template, support_version = prompt_version(
        Path("prompts/neutral_support_check_v1.md"), "neutral_support_check_v1"
    )
    counter_template, counter_version = prompt_version(
        Path("prompts/neutral_counter_check_v1.md"), "neutral_counter_check_v1"
    )
    direct_template, direct_version = prompt_version(
        Path("prompts/direct_deliberation_control_v1.md"),
        "direct_deliberation_control_v1",
    )
    selector_template, selector_version = prompt_version(
        Path("prompts/firewalled_endpoint_selector_v1.md"),
        "firewalled_endpoint_selector_v1",
    )
    cache = LLMCache(Path(config["cache_root"]).resolve())
    run_root = Path("artifacts/runs/stage5") / args.experiment_id
    output_root = run_root / "outputs"
    ledger = ExperimentLedger(
        Path("artifacts/runs/progress"),
        args.experiment_id,
        description="Neutral claim planning and rationale-firewalled endpoint selection",
    )
    failures: list[dict[str, Any]] = []
    ledger.update(
        status="running",
        phase="preparation",
        event="neutral_firewall_started",
        counts={
            "disagreement_rows": len(rows),
            "unique_cases": len(cases),
            "selector_inputs": len(selector_inputs),
            "completed": 0,
            "failed": 0,
        },
        details={
            "conditions": sorted(requested_conditions),
            "models": sorted(requested_models),
            "variants": list(requested_variants),
        },
    )

    plans: dict[str, dict[str, Any]] = {}
    if "neutral_countercheck" in requested_variants:
        plan_jobs = []
        for identity, case in sorted(cases.items()):

            def plan_job(case: dict[str, Any] = case) -> dict[str, Any]:
                model = model_configs[case["model_id"]]
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
                        "role": "stage5_neutral_claim_plan",
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
                }

            plan_jobs.append((identity, plan_job))
        plans = execute_jobs(
            plan_jobs,
            workers=args.workers,
            phase="neutral_plan",
            failures=failures,
            ledger=ledger,
        )

    method_checks: dict[tuple[str, str], dict[str, Any]] = {}
    if "neutral_countercheck" in requested_variants:
        check_jobs = []
        for identity, case in sorted(cases.items()):
            if identity not in plans:
                continue
            for role, template, version, seed in (
                ("support", support_template, support_version, 101),
                ("counter", counter_template, counter_version, 103),
            ):

                def check_job(
                    case: dict[str, Any] = case,
                    role: str = role,
                    template: str = template,
                    version: str = version,
                    seed: int = seed,
                ) -> dict[str, Any]:
                    model = model_configs[case["model_id"]]
                    plan = plans[case["case_key"]]
                    prompt = render(
                        template,
                        {
                            "CLAIM": case["claim"],
                            "CLAIM_DATE": case["claim_date"],
                            "NEUTRAL_PLAN": json.dumps(
                                plan["judgment"],
                                ensure_ascii=False,
                                sort_keys=True,
                                indent=2,
                            ),
                        },
                    )
                    request = LLMRequest(
                        stage=f"stage5_neutral_{role}_check",
                        provider=model["provider"],
                        model=model["model"],
                        prompt_id=f"neutral_{role}_check",
                        prompt_version=version,
                        messages=[{"role": "user", "content": prompt}],
                        parameters={
                            "temperature": 0.2,
                            "top_p": 0.7,
                            "max_tokens": 1200,
                            "seed": seed,
                            **model.get("request_parameters", {}),
                        },
                        response_format={"type": "json_object"},
                    )
                    judgment, receipts = execute_cached(
                        cache=cache,
                        request=request,
                        parser=parse_internal_judgment,
                        metadata={
                            "role": f"stage5_neutral_{role}_check",
                            "case_key": case["case_key"],
                            "neutral_plan_cache_key": plan["cache_key"],
                            "model_id": case["model_id"],
                        },
                        contract_name=f"neutral {role}-check contract",
                        retries=args.contract_retries,
                    )
                    return {
                        "role": role,
                        "judgment": judgment,
                        "cache_key": receipts[-1]["cache_key"],
                        "cache_hit": receipts[-1]["cache_hit"],
                    }

                check_jobs.append(((identity, role), check_job))
        method_checks = execute_jobs(
            check_jobs,
            workers=args.workers,
            phase="neutral_check",
            failures=failures,
            ledger=ledger,
        )

    direct_checks: dict[tuple[str, str], dict[str, Any]] = {}
    if "direct_deliberation" in requested_variants:
        direct_jobs = []
        for identity, case in sorted(cases.items()):
            for perspective_id, perspective, seed in DIRECT_PERSPECTIVES:

                def direct_job(
                    case: dict[str, Any] = case,
                    perspective_id: str = perspective_id,
                    perspective: str = perspective,
                    seed: int = seed,
                ) -> dict[str, Any]:
                    model = model_configs[case["model_id"]]
                    prompt = render(
                        direct_template,
                        {
                            "PERSPECTIVE": perspective,
                            "CLAIM": case["claim"],
                            "CLAIM_DATE": case["claim_date"],
                        },
                    )
                    request = LLMRequest(
                        stage="stage5_direct_deliberation_control",
                        provider=model["provider"],
                        model=model["model"],
                        prompt_id=f"direct_deliberation_{perspective_id}",
                        prompt_version=f"{direct_version}+perspective:{perspective_id}",
                        messages=[{"role": "user", "content": prompt}],
                        parameters={
                            "temperature": 0.2,
                            "top_p": 0.7,
                            "max_tokens": 1200,
                            "seed": seed,
                            **model.get("request_parameters", {}),
                        },
                        response_format={"type": "json_object"},
                    )
                    judgment, receipts = execute_cached(
                        cache=cache,
                        request=request,
                        parser=parse_internal_judgment,
                        metadata={
                            "role": "stage5_direct_deliberation_control",
                            "case_key": case["case_key"],
                            "perspective_id": perspective_id,
                            "model_id": case["model_id"],
                        },
                        contract_name="direct-deliberation control contract",
                        retries=args.contract_retries,
                    )
                    return {
                        "role": perspective_id,
                        "judgment": judgment,
                        "cache_key": receipts[-1]["cache_key"],
                        "cache_hit": receipts[-1]["cache_hit"],
                    }

                direct_jobs.append(((identity, perspective_id), direct_job))
        direct_checks = execute_jobs(
            direct_jobs,
            workers=args.workers,
            phase="direct_control",
            failures=failures,
            ledger=ledger,
        )

    variant_bundles: dict[tuple[str, str], dict[str, Any]] = {}
    for identity in sorted(cases):
        if "neutral_countercheck" in requested_variants:
            check_identities = ((identity, "support"), (identity, "counter"))
            if identity in plans and all(item in method_checks for item in check_identities):
                variant_bundles[("neutral_countercheck", identity)] = {
                    "kind": "neutral plan plus supportive and skeptical checks",
                    "visible": {
                        "neutral_plan": plans[identity]["judgment"],
                        "support_check": method_checks[(identity, "support")]["judgment"],
                        "counter_check": method_checks[(identity, "counter")]["judgment"],
                    },
                    "components": {
                        "plan_cache_key": plans[identity]["cache_key"],
                        "check_cache_keys": [
                            method_checks[(identity, "support")]["cache_key"],
                            method_checks[(identity, "counter")]["cache_key"],
                        ],
                    },
                }
        if "direct_deliberation" in requested_variants:
            direct_identities = tuple((identity, item[0]) for item in DIRECT_PERSPECTIVES)
            if all(item in direct_checks for item in direct_identities):
                variant_bundles[("direct_deliberation", identity)] = {
                    "kind": "three cost-matched direct end-claim assessments",
                    "visible": {
                        "direct_assessments": [
                            {
                                "perspective": perspective_id,
                                "judgment": direct_checks[(identity, perspective_id)]["judgment"],
                            }
                            for perspective_id, _, _ in DIRECT_PERSPECTIVES
                        ]
                    },
                    "components": {
                        "plan_cache_key": None,
                        "check_cache_keys": [
                            direct_checks[(identity, perspective_id)]["cache_key"]
                            for perspective_id, _, _ in DIRECT_PERSPECTIVES
                        ],
                    },
                }

    selector_jobs = []
    fail_closed_results: dict[tuple[str, tuple[str, str, str | None]], dict[str, Any]] = {}
    fail_closed_output_version = "stage5-contract-exhaustion-memory-v1"
    for selector_identity, selector_input in sorted(
        selector_inputs.items(), key=lambda item: repr(item[0])
    ):
        identity = selector_input["case_key"]
        for variant in requested_variants:
            bundle_identity = (variant, identity)
            if bundle_identity not in variant_bundles:
                if identity not in fail_closed_case_keys:
                    continue
                endpoint_labels = selector_input["endpoint_labels"]
                judgment = {
                    "selected_endpoint": "memory",
                    "confidence": 0.0,
                    "decisive_conflict": "The analysis workflow exhausted its structured-output contract.",
                    "proposition_check_assessment": (
                        "No complete contract-valid analysis bundle is available for endpoint selection."
                    ),
                    "rationale": "Fail closed to the pre-existing memory endpoint without parsing malformed text.",
                }
                resolved = [
                    failure
                    for failure in failures
                    if failure.get("case_key") == identity
                    and failure.get("error_type") == "ContractError"
                ]
                if not resolved:
                    continue
                resolved_receipts = [
                    receipt
                    for failure in resolved
                    if failure["phase"]
                    == ("neutral_check" if variant == "neutral_countercheck" else "direct_control")
                    for receipt in failure.get("receipts", [])
                ]
                output_key = hashlib.sha256(
                    canonical_json(
                        {
                            "workflow": "stage5-neutral-firewall-v1",
                            "variant": variant,
                            "selector_identity": selector_input["selector_identity"],
                            "resolution": fail_closed_output_version,
                            "failed_call_cache_keys": [
                                receipt["cache_key"] for receipt in resolved_receipts
                            ],
                        }
                    ).encode()
                ).hexdigest()
                prediction = endpoint_prediction(endpoint_labels, "memory")
                output = {
                    "output_schema_version": 1,
                    "workflow": "stage5-neutral-firewall-v1",
                    "variant": variant,
                    "resolution": fail_closed_output_version,
                    "output_key": output_key,
                    "case_key": identity,
                    "model_id": selector_input["model_id"],
                    "endpoint_labels": endpoint_labels,
                    "analysis_bundle": {
                        "plan_cache_key": None,
                        "check_cache_keys": [],
                        "failed_call_receipts": resolved_receipts,
                        "visible": {
                            "unavailable_reason": "structured_output_contract_exhausted"
                        },
                    },
                    "selector": {"cache_key": None, "judgment": judgment},
                    "derived_prediction": prediction,
                }
                output_path, cached_output = store_immutable_output(
                    output_root / variant, output_key, output
                )
                fail_closed_results[(variant, selector_identity)] = {
                    "output_key": output_key,
                    "output_path": str(output_path),
                    "selected_endpoint": "memory",
                    "prediction": prediction,
                    "selector_cache_key": None,
                    "cache_key": None,
                    "cache_hit": False,
                    "cached_output": cached_output,
                    "resolution": fail_closed_output_version,
                }
                continue

            def selector_job(
                variant: str = variant,
                selector_input: dict[str, Any] = selector_input,
                bundle: dict[str, Any] = variant_bundles[bundle_identity],
            ) -> dict[str, Any]:
                model = model_configs[selector_input["model_id"]]
                prompt = render(
                    selector_template,
                    {
                        "CLAIM": selector_input["claim"],
                        "CLAIM_DATE": selector_input["claim_date"],
                        "ENDPOINT_LABELS": json.dumps(
                            selector_input["endpoint_labels"],
                            ensure_ascii=False,
                            sort_keys=True,
                            indent=2,
                        ),
                        "BUNDLE_KIND": bundle["kind"],
                        "ANALYSIS_BUNDLE": json.dumps(
                            bundle["visible"],
                            ensure_ascii=False,
                            sort_keys=True,
                            indent=2,
                        ),
                    },
                )
                request = LLMRequest(
                    stage="stage5_firewalled_endpoint_selector",
                    provider=model["provider"],
                    model=model["model"],
                    prompt_id=f"firewalled_endpoint_selector_{variant}",
                    prompt_version=f"{selector_version}+bundle:{variant}",
                    messages=[{"role": "user", "content": prompt}],
                    parameters={
                        "temperature": 0.2,
                        "top_p": 0.7,
                        "max_tokens": 1000,
                        "seed": 107,
                        **model.get("request_parameters", {}),
                    },
                    response_format={"type": "json_object"},
                )
                judgment, receipts = execute_cached(
                    cache=cache,
                    request=request,
                    parser=parse_aligned_final_text,
                    metadata={
                        "role": "stage5_firewalled_endpoint_selector",
                        "case_key": selector_input["case_key"],
                        "model_id": selector_input["model_id"],
                        "bundle_variant": variant,
                        **bundle["components"],
                    },
                    contract_name="firewalled endpoint-selector contract",
                    retries=args.contract_retries,
                )
                selected_endpoint = judgment["selected_endpoint"]
                prediction = endpoint_prediction(
                    selector_input["endpoint_labels"], selected_endpoint
                )
                output_key = hashlib.sha256(
                    canonical_json(
                        {
                            "workflow": "stage5-neutral-firewall-v1",
                            "variant": variant,
                            "selector_identity": selector_input["selector_identity"],
                            **bundle["components"],
                            "selector_cache_key": receipts[-1]["cache_key"],
                            "plan_contract": (
                                NEUTRAL_PLAN_CONTRACT_VERSION
                                if variant == "neutral_countercheck"
                                else None
                            ),
                            "selector_contract": FIREWALLED_SELECTOR_CONTRACT_VERSION,
                        }
                    ).encode()
                ).hexdigest()
                output = {
                    "output_schema_version": 1,
                    "workflow": "stage5-neutral-firewall-v1",
                    "variant": variant,
                    "output_key": output_key,
                    "case_key": selector_input["case_key"],
                    "model_id": selector_input["model_id"],
                    "endpoint_labels": selector_input["endpoint_labels"],
                    "analysis_bundle": {
                        **bundle["components"],
                        "visible": bundle["visible"],
                    },
                    "selector": {
                        "cache_key": receipts[-1]["cache_key"],
                        "judgment": judgment,
                    },
                    "derived_prediction": prediction,
                }
                output_path, cached_output = store_immutable_output(
                    output_root / variant, output_key, output
                )
                return {
                    "output_key": output_key,
                    "output_path": str(output_path),
                    "selected_endpoint": selected_endpoint,
                    "prediction": prediction,
                    "selector_cache_key": receipts[-1]["cache_key"],
                    "cache_key": receipts[-1]["cache_key"],
                    "cache_hit": receipts[-1]["cache_hit"],
                    "cached_output": cached_output,
                }

            selector_jobs.append(((variant, selector_identity), selector_job))
    selector_results = execute_jobs(
        selector_jobs,
        workers=args.workers,
        phase="firewalled_selector",
        failures=failures,
        ledger=ledger,
    )
    selector_results.update(fail_closed_results)

    resolved_failures = [
        failure
        for failure in failures
        if failure.get("case_key") in fail_closed_case_keys
        and failure.get("error_type") == "ContractError"
    ]
    unresolved_failures = [failure for failure in failures if failure not in resolved_failures]

    outputs: list[dict[str, Any]] = []
    for row in rows:
        for variant in requested_variants:
            result_identity = (variant, row["selector_identity"])
            if result_identity not in selector_results:
                continue
            result = selector_results[result_identity]
            outputs.append(
                {
                    "claim_id": row["claim_id"],
                    "victim_model_id": row["victim_model_id"],
                    "condition_id": row["condition_id"],
                    "aligned_packet_key": row["aligned_packet_key"],
                    "aligned_packet_path": row["aligned_packet_path"],
                    "case_key": row["case_key"],
                    "variant": variant,
                    **result,
                }
            )
    outputs.sort(
        key=lambda row: (
            row["claim_id"],
            row["victim_model_id"],
            row["condition_id"],
            row["variant"],
        )
    )
    output_variant_counts = Counter(row["variant"] for row in outputs)
    manifest_path = run_root / "private_manifest.json"
    atomic_json(
        manifest_path,
        {
            "warning": "PRIVATE METADATA: never serialize condition/model/attacker fields into prompts",
            "experiment_id": args.experiment_id,
            "workflow": "stage5-neutral-firewall-v1",
            "source_router_experiment": router_manifest["experiment_id"],
            "conditions": sorted(requested_conditions),
            "models": sorted(requested_models),
            "variants": list(requested_variants),
            "disagreement_rows": len(rows),
            "unique_model_claim_cases": len(cases),
            "unique_endpoint_label_inputs": len(selector_inputs),
            "expected_output_rows": expected_output_rows,
            "output_variant_counts": dict(sorted(output_variant_counts.items())),
            "maximum_new_calls_by_variant": {
                variant: expected_calls[variant] for variant in requested_variants
            },
            "fail_closed_case_keys": sorted(fail_closed_case_keys),
            "fail_closed_resolution": fail_closed_output_version,
            "resolved_failures": resolved_failures,
            "outputs": outputs,
            "failures": unresolved_failures,
        },
    )
    status = (
        "complete"
        if not unresolved_failures and len(outputs) == expected_output_rows
        else "failed"
    )
    ledger.update(
        status=status,
        phase="firewalled_selector",
        event=(
            "neutral_firewall_completed" if status == "complete" else "neutral_firewall_failed"
        ),
        counts={
            "disagreement_rows": len(rows),
            "expected_outputs": expected_output_rows,
            "completed": len(outputs),
            "failed": len(unresolved_failures),
            "resolved_failures": len(resolved_failures),
        },
        artifacts={"manifest": str(manifest_path)},
    )
    print(
        json.dumps(
            {
                "status": status,
                **preparation,
                "outputs": len(outputs),
                "failures": len(unresolved_failures),
                "resolved_failures": len(resolved_failures),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if status != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
