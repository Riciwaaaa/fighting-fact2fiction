#!/usr/bin/env python3
"""Run proposition-structured Stage 4 v2 or its equal-call direct control."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import traceback
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from parametric_rag_defense.aligned_workflow import candidate_prediction
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import LLMCache, LLMRequest, canonical_json
from parametric_rag_defense.contracts import parse_internal_judgment
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.stage4_v2 import (
    ADJUDICATOR_CONTRACT_VERSION,
    ARCHITECT_CONTRACT_VERSION,
    parse_adjudicator_text,
    parse_architect_text,
    validate_action_verdict,
)
from parametric_rag_defense.workflow_runtime import (
    execute_cached,
    prompt_version,
    render,
    store_immutable_output,
)

PROPOSITION_SEEDS = {"claim_core": (211, 223), "discriminator": (227, 229)}
DIRECT_SEEDS = (101, 211, 223, 227, 229)


def check_summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute non-LLM counts so the adjudicator cannot infer or relabel check bases."""

    by_proposition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for check in checks:
        identifier = check["proposition"]["id"] if check["proposition"] else "direct_end_claim"
        by_proposition[identifier].append(check)
    result = {}
    for identifier, group in sorted(by_proposition.items()):
        result[identifier] = {
            "samples": len(group),
            "verdict_counts": dict(sorted(Counter(item["judgment"]["verdict"] for item in group).items())),
            "knowledge_basis_counts": dict(
                sorted(Counter(item["judgment"]["knowledge_basis"] for item in group).items())
            ),
            "unanimous_verdict": len({item["judgment"]["verdict"] for item in group}) == 1,
        }
    return result


def effect_summary(plan: dict[str, Any], checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply proposition-to-claim mappings deterministically before LLM synthesis."""

    propositions = {item["id"]: item for item in plan["propositions"]}
    rows = []
    effects: Counter[str] = Counter()
    for check in checks:
        proposition = propositions[check["proposition"]["id"]]
        verdict = check["judgment"]["verdict"]
        effect = (
            proposition["effect_if_supported"]
            if verdict == "Supported"
            else proposition["effect_if_refuted"]
            if verdict == "Refuted"
            else "undetermined"
        )
        effects[effect] += 1
        rows.append(
            {
                "proposition_id": proposition["id"],
                "role": proposition["role"],
                "check_verdict": verdict,
                "knowledge_basis": check["judgment"]["knowledge_basis"],
                "logical_effect_on_claim": effect,
            }
        )
    return {"effect_counts": dict(sorted(effects.items())), "mapped_checks": rows}


def endpoint_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Return endpoint summaries without retrieved excerpts or provenance."""

    retrieval = packet["visible"]["retrieval_assessment"]
    return {
        "claim": packet["visible"]["claim"],
        "claim_date": packet["visible"]["claim_date"],
        "retrieval_endpoint": {
            key: retrieval[key]
            for key in ("verdict", "confidence", "rationale", "coverage")
        },
        "memory_endpoint": packet["visible"]["memory_only_assessment"],
    }


def minimal_endpoint_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Withhold every rationale and proposition from the firewalled selector."""

    retrieval = packet["visible"]["retrieval_assessment"]
    memory = packet["visible"]["memory_only_assessment"]
    return {
        "retrieval": {
            "verdict": retrieval["verdict"],
            "confidence": retrieval["confidence"],
            "coverage": retrieval["coverage"],
        },
        "memory": {
            "leading_verdicts": memory["leading_verdicts"],
            "verdict_distribution": memory["verdict_distribution"],
            "agreement_fraction": memory["agreement_fraction"],
            "mean_confidence": memory["mean_confidence"],
            "knowledge_basis_distribution": memory["knowledge_basis_distribution"],
            "repeat_count": memory["repeat_count"],
        },
    }


def execute_jobs(
    jobs: list[tuple[Any, Callable[[], dict[str, Any]]]],
    *,
    workers: int,
    phase: str,
    failures: list[dict[str, Any]],
) -> dict[Any, dict[str, Any]]:
    results: dict[Any, dict[str, Any]] = {}
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
                failures.append(
                    {
                        "phase": phase,
                        "identity": repr(identity),
                        "error": repr(exc),
                        "traceback": traceback.format_exc(),
                    }
                )
                print(f"{phase} {completed}/{len(jobs)} FAILED identity={identity}: {exc}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("proposition", "direct_control"))
    parser.add_argument("--stage1-config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--router-root", type=Path, default=Path("artifacts/runs/stage3/stage3_same_model_ab_v1")
    )
    parser.add_argument("--variant", default="endpoint_only", choices=("endpoint_only", "evidence_aware"))
    parser.add_argument("--experiment-id")
    parser.add_argument("--conditions", default="clean,fact2fiction_p0.01")
    parser.add_argument("--models", default="llama31_70b")
    parser.add_argument("--claims", help="Optional comma-separated claim-ID subset")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--contract-retries", type=int, default=2)
    args = parser.parse_args()
    if args.workers < 1 or args.contract_retries < 0:
        raise SystemExit("workers must be positive and contract retries nonnegative")
    experiment_id = args.experiment_id or (
        "stage4_same_model_v2" if args.mode == "proposition" else "stage4_direct_control_v1"
    )

    config_path = args.stage1_config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    load_dotenv(config_path.parent.parent / ".env")
    model_configs = {
        model["id"]: model
        for model in config["models"]
        if model.get("enabled") and "arbiter" in model["roles"]
    }
    requested_models = set(args.models.split(","))
    missing_models = requested_models - set(model_configs)
    if missing_models:
        raise SystemExit(f"Unknown same-model configurations: {sorted(missing_models)}")
    conditions = set(args.conditions.split(","))
    selected_claims = set(map(int, args.claims.split(","))) if args.claims else None

    router_manifest = json.loads(
        (args.router_root / "private_manifest.json").read_text(encoding="utf-8")
    )
    if router_manifest["dry_run"] or router_manifest["failures"]:
        raise ValueError("Router manifest is dry-run or contains failures")
    rows = []
    for row in router_manifest["outputs"]:
        if (
            row["variant"] != args.variant
            or row["victim_model_id"] not in requested_models
            or row["condition_id"] not in conditions
            or (selected_claims is not None and int(row["claim_id"]) not in selected_claims)
        ):
            continue
        packet = json.loads(Path(row["aligned_packet_path"]).read_text(encoding="utf-8"))
        router = json.loads(Path(row["output_path"]).read_text(encoding="utf-8"))
        retrieval_verdict = packet["visible"]["retrieval_assessment"]["verdict"]
        memory_verdict = candidate_prediction(packet["visible"]["memory_only_assessment"])
        if memory_verdict is None:
            raise ValueError(f"Ambiguous same-model memory endpoint for claim {row['claim_id']}")
        if retrieval_verdict == memory_verdict:
            continue
        rows.append(
            {
                **row,
                "packet": packet,
                "router_output": router,
                "endpoint_packet": endpoint_packet(packet),
                "retrieval_verdict": retrieval_verdict,
                "memory_verdict": memory_verdict,
            }
        )
    rows.sort(key=lambda row: (row["claim_id"], row["victim_model_id"], row["condition_id"]))
    if not rows:
        raise SystemExit("No endpoint disagreements match the requested scope")

    architect_template, architect_version = prompt_version(
        Path("prompts/stage4_proposition_architect_v2.md"), "stage4_proposition_architect_v2"
    )
    proposition_template, proposition_version = prompt_version(
        Path("prompts/stage4_proposition_check_v2.md"), "stage4_proposition_check_v2"
    )
    internal_template, internal_version = prompt_version(
        Path("prompts/internal_claim_v2.md"), "internal_claim_v2"
    )
    synthesis_path = (
        Path("prompts/stage4_internal_synthesizer_v2.md")
        if args.mode == "proposition"
        else Path("prompts/stage4_direct_synthesizer_v1.md")
    )
    synthesis_identifier = (
        "stage4_internal_synthesizer_v2"
        if args.mode == "proposition"
        else "stage4_direct_synthesizer_v1"
    )
    synthesis_template, synthesis_version = prompt_version(
        synthesis_path, synthesis_identifier
    )
    final_template, final_version = prompt_version(
        Path("prompts/stage4_firewalled_selector_v2.md"),
        "stage4_firewalled_selector_v2",
    )

    cache = LLMCache(Path(config["cache_root"]).resolve())
    run_root = Path("artifacts/runs/stage4") / experiment_id
    output_root = run_root / "outputs"
    ledger = ExperimentLedger(
        Path("artifacts/runs/progress"),
        experiment_id,
        description=f"Stage 4 v2 same-model {args.mode} workflow",
    )
    failures: list[dict[str, Any]] = []
    ledger.update(
        status="running",
        phase="preparation",
        event="stage4_v2_started",
        counts={"disagreements": len(rows), "completed": 0, "failed": 0},
        details={
            "mode": args.mode,
            "variant": args.variant,
            "models": sorted(requested_models),
            "conditions": sorted(conditions),
        },
    )

    architects: dict[str, dict[str, Any]] = {}
    if args.mode == "proposition":
        jobs = []
        for row in rows:
            def architect_job(row: dict[str, Any] = row) -> dict[str, Any]:
                model = model_configs[row["victim_model_id"]]
                endpoint = row["endpoint_packet"]
                prompt = render(
                    architect_template,
                    {
                        "CLAIM": endpoint["claim"],
                        "CLAIM_DATE": endpoint["claim_date"],
                        "RETRIEVAL_ENDPOINT": json.dumps(
                            endpoint["retrieval_endpoint"], ensure_ascii=False, sort_keys=True, indent=2
                        ),
                        "MEMORY_ENDPOINT": json.dumps(
                            endpoint["memory_endpoint"], ensure_ascii=False, sort_keys=True, indent=2
                        ),
                        "ROUTER_JUDGMENT": json.dumps(
                            row["router_output"]["router"]["judgment"],
                            ensure_ascii=False,
                            sort_keys=True,
                            indent=2,
                        ),
                    },
                )
                request = LLMRequest(
                    stage="stage4_v2_architect",
                    provider=model["provider"],
                    model=model["model"],
                    prompt_id="stage4_proposition_architect",
                    prompt_version=architect_version,
                    messages=[{"role": "user", "content": prompt}],
                    parameters={
                        "temperature": 0.2,
                        "top_p": 0.7,
                        "max_tokens": 1500,
                        "seed": 101,
                        **model.get("request_parameters", {}),
                    },
                    response_format={"type": "json_object"},
                )
                judgment, receipts = execute_cached(
                    cache=cache,
                    request=request,
                    parser=parse_architect_text,
                    metadata={
                        "role": "stage4_v2_architect",
                        "aligned_packet_key": row["packet"]["packet_key"],
                        "router_output_key": row["router_output"]["output_key"],
                        "model_id": row["victim_model_id"],
                        "variant": args.variant,
                    },
                    contract_name="Stage 4 v2 architect contract",
                    retries=args.contract_retries,
                )
                return {
                    "judgment": judgment,
                    "cache_key": receipts[-1]["cache_key"],
                    "cache_hit": receipts[-1]["cache_hit"],
                }

            jobs.append((row["packet"]["packet_key"], architect_job))
        architects = execute_jobs(
            jobs, workers=args.workers, phase="architect", failures=failures
        )

    factual_checks: dict[tuple[str, str, int], dict[str, Any]] = {}
    check_jobs = []
    for row in rows:
        packet_key = row["packet"]["packet_key"]
        model = model_configs[row["victim_model_id"]]
        if args.mode == "proposition":
            if packet_key not in architects:
                continue
            specifications = [
                (proposition, seed)
                for proposition in architects[packet_key]["judgment"]["propositions"]
                for seed in PROPOSITION_SEEDS[proposition["role"]]
            ]
        else:
            specifications = [(None, seed) for seed in DIRECT_SEEDS]
        for proposition, seed in specifications:
            proposition_id = proposition["id"] if proposition is not None else "direct"

            def check_job(
                row: dict[str, Any] = row,
                model: dict[str, Any] = model,
                proposition: dict[str, Any] | None = proposition,
                seed: int = seed,
            ) -> dict[str, Any]:
                endpoint = row["endpoint_packet"]
                if proposition is None:
                    prompt = render(
                        internal_template,
                        {"CLAIM": endpoint["claim"], "CLAIM_DATE": endpoint["claim_date"]},
                    )
                    prompt_id = "stage4_direct_control_claim"
                    prompt_version_value = f"{internal_version}+stage4-direct-control"
                    stage = "stage4_direct_control_claim"
                else:
                    prompt = render(
                        proposition_template,
                        {
                            "CLAIM": endpoint["claim"],
                            "CLAIM_DATE": endpoint["claim_date"],
                            "PROPOSITION_ROLE": proposition["role"],
                            "PROPOSITION": proposition["text"],
                        },
                    )
                    prompt_id = "stage4_proposition_check_v2"
                    prompt_version_value = proposition_version
                    stage = "stage4_v2_proposition_check"
                request = LLMRequest(
                    stage=stage,
                    provider=model["provider"],
                    model=model["model"],
                    prompt_id=prompt_id,
                    prompt_version=prompt_version_value,
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
                        "role": stage,
                        "aligned_packet_key": row["packet"]["packet_key"],
                        "router_output_key": row["router_output"]["output_key"],
                        "model_id": row["victim_model_id"],
                        "variant": args.variant,
                        "proposition_id": proposition["id"] if proposition is not None else None,
                        "seed": seed,
                    },
                    contract_name="Stage 4 v2 factual-check contract",
                    retries=args.contract_retries,
                )
                return {
                    "judgment": judgment,
                    "cache_key": receipts[-1]["cache_key"],
                    "cache_hit": receipts[-1]["cache_hit"],
                    "seed": seed,
                    "proposition": proposition,
                }

            identity = (packet_key, proposition_id, seed)
            check_jobs.append((identity, check_job))
    factual_checks = execute_jobs(
        check_jobs, workers=args.workers, phase="factual_check", failures=failures
    )

    prepared_rows: dict[str, dict[str, Any]] = {}
    synthesis_jobs = []
    for row in rows:
        packet_key = row["packet"]["packet_key"]
        if args.mode == "proposition":
            if packet_key not in architects:
                continue
            plan = architects[packet_key]["judgment"]
            identities = [
                (packet_key, proposition["id"], seed)
                for proposition in plan["propositions"]
                for seed in PROPOSITION_SEEDS[proposition["role"]]
            ]
        else:
            plan = None
            identities = [(packet_key, "direct", seed) for seed in DIRECT_SEEDS]
        if any(identity not in factual_checks for identity in identities):
            continue
        row_checks = [factual_checks[identity] for identity in identities]

        def synthesis_job(
            row: dict[str, Any] = row,
            plan: dict[str, Any] | None = plan,
            row_checks: list[dict[str, Any]] = row_checks,
        ) -> dict[str, Any]:
            model = model_configs[row["victim_model_id"]]
            if args.mode == "proposition":
                replacements = {
                    "CLAIM": row["endpoint_packet"]["claim"],
                    "CLAIM_DATE": row["endpoint_packet"]["claim_date"],
                    "PROPOSITION_PLAN": json.dumps(
                        plan, ensure_ascii=False, sort_keys=True, indent=2
                    ),
                    "PROPOSITION_CHECKS": json.dumps(
                        [
                            {
                                "proposition_id": check["proposition"]["id"],
                                "role": check["proposition"]["role"],
                                "seed": check["seed"],
                                "judgment": check["judgment"],
                            }
                            for check in row_checks
                        ],
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    ),
                    "EFFECT_SUMMARY": json.dumps(
                        effect_summary(plan, row_checks),
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    ),
                }
            else:
                replacements = {
                    "CLAIM": row["endpoint_packet"]["claim"],
                    "CLAIM_DATE": row["endpoint_packet"]["claim_date"],
                    "DIRECT_JUDGMENTS": json.dumps(
                        [
                            {
                                "sample_id": index + 1,
                                "seed": check["seed"],
                                "judgment": check["judgment"],
                            }
                            for index, check in enumerate(row_checks)
                        ],
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    ),
                    "CHECK_SUMMARY": json.dumps(
                        check_summary(row_checks),
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    ),
                }
            prompt = render(synthesis_template, replacements)
            request = LLMRequest(
                stage=(
                    "stage4_v2_internal_synthesis"
                    if args.mode == "proposition"
                    else "stage4_direct_control_synthesis"
                ),
                provider=model["provider"],
                model=model["model"],
                prompt_id=synthesis_identifier,
                prompt_version=synthesis_version,
                messages=[{"role": "user", "content": prompt}],
                parameters={
                    "temperature": 0.2,
                    "top_p": 0.7,
                    "max_tokens": 1400,
                    "seed": 263,
                    **model.get("request_parameters", {}),
                },
                response_format={"type": "json_object"},
            )
            judgment, receipts = execute_cached(
                cache=cache,
                request=request,
                parser=parse_internal_judgment,
                metadata={
                    "role": (
                        "stage4_v2_internal_synthesis"
                        if args.mode == "proposition"
                        else "stage4_direct_control_synthesis"
                    ),
                    "aligned_packet_key": row["packet"]["packet_key"],
                    "model_id": row["victim_model_id"],
                    "variant": args.variant,
                },
                contract_name="Stage 4 retrieval-isolated synthesis contract",
                retries=args.contract_retries,
            )
            return {
                "judgment": judgment,
                "cache_key": receipts[-1]["cache_key"],
                "cache_hit": receipts[-1]["cache_hit"],
            }

        prepared_rows[packet_key] = {
            "row": row,
            "plan": plan,
            "checks": row_checks,
        }
        synthesis_jobs.append((packet_key, synthesis_job))

    syntheses = execute_jobs(
        synthesis_jobs, workers=args.workers, phase="internal_synthesis", failures=failures
    )

    outputs: list[dict[str, Any]] = []
    final_jobs = []
    for packet_key, prepared in prepared_rows.items():
        if packet_key not in syntheses:
            continue
        row = prepared["row"]
        plan = prepared["plan"]
        row_checks = prepared["checks"]
        synthesis = syntheses[packet_key]

        def final_job(
            packet_key: str = packet_key,
            row: dict[str, Any] = row,
            plan: dict[str, Any] | None = plan,
            row_checks: list[dict[str, Any]] = row_checks,
            synthesis: dict[str, Any] = synthesis,
        ) -> dict[str, Any]:
            model = model_configs[row["victim_model_id"]]
            prompt = render(
                final_template,
                {
                    "CLAIM": row["endpoint_packet"]["claim"],
                    "CLAIM_DATE": row["endpoint_packet"]["claim_date"],
                    "MINIMAL_ENDPOINTS": json.dumps(
                        minimal_endpoint_packet(row["packet"]),
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    ),
                    "INTERNAL_SYNTHESIS": json.dumps(
                        synthesis["judgment"],
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    ),
                },
            )
            request = LLMRequest(
                stage="stage4_firewalled_selector",
                provider=model["provider"],
                model=model["model"],
                prompt_id="stage4_firewalled_selector_v2",
                prompt_version=final_version,
                messages=[{"role": "user", "content": prompt}],
                parameters={
                    "temperature": 0.2,
                    "top_p": 0.7,
                    "max_tokens": 1200,
                    "seed": 307,
                    **model.get("request_parameters", {}),
                },
                response_format={"type": "json_object"},
            )
            judgment, receipts = execute_cached(
                cache=cache,
                request=request,
                parser=parse_adjudicator_text,
                metadata={
                    "role": "stage4_firewalled_selector",
                    "aligned_packet_key": row["packet"]["packet_key"],
                    "model_id": row["victim_model_id"],
                    "variant": args.variant,
                    "mode": args.mode,
                },
                contract_name="Stage 4 firewalled-selector contract",
                retries=args.contract_retries,
            )
            validate_action_verdict(
                judgment,
                retrieval_verdict=row["retrieval_verdict"],
                memory_verdict=row["memory_verdict"],
                internal_verdict=synthesis["judgment"]["verdict"],
            )
            component_keys = {
                "architect_cache_key": architects[packet_key]["cache_key"] if plan is not None else None,
                "factual_check_cache_keys": [check["cache_key"] for check in row_checks],
                "synthesis_cache_key": synthesis["cache_key"],
                "final_cache_key": receipts[-1]["cache_key"],
            }
            output_key = hashlib.sha256(
                canonical_json(
                    {
                        "mode": args.mode,
                        "aligned_packet_key": packet_key,
                        "router_output_key": row["router_output"]["output_key"],
                        **component_keys,
                        "architect_contract": ARCHITECT_CONTRACT_VERSION if plan is not None else None,
                        "adjudicator_contract": ADJUDICATOR_CONTRACT_VERSION,
                    }
                ).encode()
            ).hexdigest()
            output = {
                "output_schema_version": 2,
                "mode": args.mode,
                "output_key": output_key,
                "aligned_packet_key": packet_key,
                "router_output_key": row["router_output"]["output_key"],
                "architect": ({**architects[packet_key]} if plan is not None else None),
                "factual_checks": row_checks,
                "internal_synthesis": synthesis,
                "adjudicator": {
                    "model_id": row["victim_model_id"],
                    "cache_key": receipts[-1]["cache_key"],
                    "judgment": judgment,
                },
                "derived_prediction": judgment["verdict"],
            }
            output_path, cached_output = store_immutable_output(output_root, output_key, output)
            return {
                "output_key": output_key,
                "output_path": str(output_path),
                "prediction": judgment["verdict"],
                "internal_prediction": synthesis["judgment"]["verdict"],
                "action": judgment["action"],
                "synthesis_cache_key": synthesis["cache_key"],
                "final_cache_key": receipts[-1]["cache_key"],
                "final_cache_hit": receipts[-1]["cache_hit"],
                "cached_output": cached_output,
            }

        final_jobs.append((packet_key, final_job))

    final_results = execute_jobs(
        final_jobs, workers=args.workers, phase="firewalled_selector", failures=failures
    )
    for row in rows:
        packet_key = row["packet"]["packet_key"]
        if packet_key not in final_results:
            continue
        outputs.append(
            {
                "claim_id": row["claim_id"],
                "victim_model_id": row["victim_model_id"],
                "condition_id": row["condition_id"],
                "variant": args.variant,
                "aligned_packet_key": packet_key,
                "aligned_packet_path": row["aligned_packet_path"],
                "router_output_key": row["router_output"]["output_key"],
                "router_output_path": row["output_path"],
                **final_results[packet_key],
            }
        )
    outputs.sort(key=lambda row: (row["claim_id"], row["victim_model_id"], row["condition_id"]))
    manifest_path = run_root / "private_manifest.json"
    atomic_json(
        manifest_path,
        {
            "warning": "PRIVATE METADATA: never serialize condition/model fields into prompts",
            "experiment_id": experiment_id,
            "mode": args.mode,
            "router_experiment_id": router_manifest["experiment_id"],
            "variant": args.variant,
            "models": sorted(requested_models),
            "conditions": sorted(conditions),
            "target_disagreements": len(rows),
            "expected_calls_per_disagreement": 7,
            "outputs": outputs,
            "failures": failures,
        },
    )
    status = "complete" if not failures and len(outputs) == len(rows) else "failed"
    ledger.update(
        status=status,
        phase="firewalled_selector",
        event="stage4_v2_completed" if status == "complete" else "stage4_v2_failed",
        counts={"disagreements": len(rows), "completed": len(outputs), "failed": len(failures)},
        artifacts={"manifest": str(manifest_path)},
    )
    print(
        json.dumps(
            {
                "status": status,
                "mode": args.mode,
                "disagreements": len(rows),
                "outputs": len(outputs),
                "failures": len(failures),
            },
            indent=2,
        )
    )
    if status != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
