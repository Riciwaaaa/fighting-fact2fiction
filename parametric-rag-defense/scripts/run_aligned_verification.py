#!/usr/bin/env python3
"""Run targeted same-model proposition checks and final endpoint selection."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import traceback
from pathlib import Path
from typing import Any

from parametric_rag_defense.aligned_workflow import (
    ALIGNED_FINAL_CONTRACT_VERSION,
    candidate_prediction,
    parse_aligned_final_text,
    selected_prediction,
)
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import LLMCache, LLMRequest, canonical_json
from parametric_rag_defense.contracts import parse_internal_judgment
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.workflow_runtime import (
    execute_cached,
    prompt_version,
    render,
    store_immutable_output,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1-config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--router-root", type=Path, default=Path("artifacts/runs/stage3/stage3_same_model_ab_v1")
    )
    parser.add_argument("--variant", required=True, choices=("endpoint_only", "evidence_aware"))
    parser.add_argument("--experiment-id", default="stage4_same_model_c_v1")
    parser.add_argument("--conditions", default="clean,fact2fiction_p0.01")
    parser.add_argument("--models", help="Optional comma-separated model-ID subset")
    parser.add_argument("--claims", help="Optional comma-separated claim-ID subset")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--contract-retries", type=int, default=2)
    args = parser.parse_args()
    if args.workers < 1 or args.contract_retries < 0:
        raise SystemExit("workers must be positive and contract retries nonnegative")

    config_path = args.stage1_config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    load_dotenv(config_path.parent.parent / ".env")
    models = {
        model["id"]: model
        for model in config["models"]
        if model.get("enabled") and "arbiter" in model["roles"]
    }
    requested_models = set(args.models.split(",")) if args.models else set(models)
    conditions = set(args.conditions.split(","))
    selected_claims = set(int(value) for value in args.claims.split(",")) if args.claims else None
    manifest = json.loads((args.router_root / "private_manifest.json").read_text(encoding="utf-8"))
    if manifest["dry_run"] or manifest["failures"]:
        raise ValueError("Router manifest is dry-run or contains failures")
    rows = []
    for row in manifest["outputs"]:
        if row["variant"] != args.variant or row["condition_id"] not in conditions:
            continue
        if row["victim_model_id"] not in requested_models:
            continue
        if selected_claims is not None and int(row["claim_id"]) not in selected_claims:
            continue
        packet = json.loads(Path(row["aligned_packet_path"]).read_text(encoding="utf-8"))
        memory = candidate_prediction(packet["visible"]["memory_only_assessment"])
        rag = packet["visible"]["retrieval_assessment"]["verdict"]
        if rag == memory:
            continue
        router_output = json.loads(Path(row["output_path"]).read_text(encoding="utf-8"))
        rows.append({**row, "packet": packet, "router_output": router_output})
    rows.sort(key=lambda row: (row["claim_id"], row["victim_model_id"], row["condition_id"]))
    if not rows:
        raise SystemExit("No endpoint disagreements match the requested Stage C scope")

    proposition_template, proposition_version = prompt_version(
        Path("prompts/aligned_proposition_check_v1.md"), "aligned_proposition_check_v1"
    )
    final_template, final_version = prompt_version(
        Path("prompts/aligned_final_arbiter_v1.md"), "aligned_final_arbiter_v1"
    )
    cache = LLMCache(Path(config["cache_root"]).resolve())
    run_root = Path("artifacts/runs/stage4") / args.experiment_id
    output_root = run_root / "outputs"
    ledger = ExperimentLedger(
        Path("artifacts/runs/progress"),
        args.experiment_id,
        description="Targeted same-model pivotal-proposition check and endpoint selection",
    )
    failures: list[dict[str, Any]] = []
    checks: dict[str, dict[str, Any]] = {}
    ledger.update(
        status="running",
        phase="proposition_check",
        event="aligned_verification_started",
        counts={"disagreements": len(rows), "checks": 0, "finals": 0, "failed": 0},
        details={"variant": args.variant, "conditions": sorted(conditions), "models": sorted(requested_models)},
    )

    def check_job(row: dict[str, Any]) -> dict[str, Any]:
        model = models[row["victim_model_id"]]
        visible = row["packet"]["visible"]
        proposition = row["router_output"]["router"]["judgment"]["pivotal_proposition"]
        if proposition.strip().lower() == "none":
            proposition = "Whether the original claim's central factual assertion is accurate as stated."
        prompt = render(
            proposition_template,
            {
                "CLAIM": visible["claim"],
                "CLAIM_DATE": visible["claim_date"],
                "PROPOSITION": proposition,
            },
        )
        request = LLMRequest(
            stage="stage4_aligned_proposition_check",
            provider=model["provider"],
            model=model["model"],
            prompt_id="aligned_proposition_check",
            prompt_version=proposition_version,
            messages=[{"role": "user", "content": prompt}],
            parameters={
                "temperature": 0.2,
                "top_p": 0.7,
                "max_tokens": 1200,
                "seed": 71,
                **model.get("request_parameters", {}),
            },
            response_format={"type": "json_object"},
        )
        judgment, receipts = execute_cached(
            cache=cache,
            request=request,
            parser=parse_internal_judgment,
            metadata={
                "role": "aligned_same_model_proposition_check",
                "aligned_packet_key": row["packet"]["packet_key"],
                "router_output_key": row["router_output"]["output_key"],
                "model_id": row["victim_model_id"],
                "variant": args.variant,
            },
            contract_name="proposition-check contract",
            retries=args.contract_retries,
        )
        return {
            "proposition": proposition,
            "judgment": judgment,
            "cache_key": receipts[-1]["cache_key"],
            "cache_hit": receipts[-1]["cache_hit"],
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_rows = {executor.submit(check_job, row): row for row in rows}
        for completed, future in enumerate(concurrent.futures.as_completed(future_rows), 1):
            row = future_rows[future]
            try:
                checks[row["packet"]["packet_key"]] = future.result()
                print(
                    f"check {completed}/{len(rows)} model={row['victim_model_id']} "
                    f"claim={row['claim_id']} condition={row['condition_id']} "
                    f"cached={checks[row['packet']['packet_key']]['cache_hit']}"
                )
            except Exception as exc:
                failures.append(
                    {
                        "phase": "proposition_check",
                        "claim_id": row["claim_id"],
                        "model_id": row["victim_model_id"],
                        "condition_id": row["condition_id"],
                        "error": repr(exc),
                        "traceback": traceback.format_exc(),
                    }
                )
                print(f"check {completed}/{len(rows)} FAILED claim={row['claim_id']}: {exc}")
            if completed % 10 == 0 or completed == len(rows):
                ledger.update(
                    status="running" if not failures else "failed",
                    phase="proposition_check",
                    event="aligned_check_progress",
                    counts={"disagreements": len(rows), "checks": len(checks), "finals": 0, "failed": len(failures)},
                )

    outputs: list[dict[str, Any]] = []

    def final_job(row: dict[str, Any]) -> dict[str, Any]:
        model = models[row["victim_model_id"]]
        packet = row["packet"]
        check = checks[packet["packet_key"]]
        prompt = render(
            final_template,
            {
                "ALIGNED_PACKET": json.dumps(packet["visible"], ensure_ascii=False, sort_keys=True, indent=2),
                "ROUTER_JUDGMENT": json.dumps(
                    row["router_output"]["router"]["judgment"],
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                ),
                "PROPOSITION_CHECK": json.dumps(check["judgment"], ensure_ascii=False, sort_keys=True, indent=2),
            },
        )
        request = LLMRequest(
            stage="stage4_aligned_final_selector",
            provider=model["provider"],
            model=model["model"],
            prompt_id="aligned_final_arbiter",
            prompt_version=final_version,
            messages=[{"role": "user", "content": prompt}],
            parameters={
                "temperature": 0.2,
                "top_p": 0.7,
                "max_tokens": 1000,
                "seed": 83,
                **model.get("request_parameters", {}),
            },
            response_format={"type": "json_object"},
        )
        judgment, receipts = execute_cached(
            cache=cache,
            request=request,
            parser=parse_aligned_final_text,
            metadata={
                "role": "aligned_same_model_final_selector",
                "aligned_packet_key": packet["packet_key"],
                "router_output_key": row["router_output"]["output_key"],
                "proposition_cache_key": check["cache_key"],
                "model_id": row["victim_model_id"],
                "variant": args.variant,
            },
            contract_name="aligned final-selector contract",
            retries=args.contract_retries,
        )
        prediction = selected_prediction(packet, judgment["selected_endpoint"])
        output_key = hashlib.sha256(
            canonical_json(
                {
                    "aligned_packet_key": packet["packet_key"],
                    "router_output_key": row["router_output"]["output_key"],
                    "proposition_cache_key": check["cache_key"],
                    "final_cache_key": receipts[-1]["cache_key"],
                    "contract_version": ALIGNED_FINAL_CONTRACT_VERSION,
                }
            ).encode()
        ).hexdigest()
        output = {
            "output_schema_version": 1,
            "contract_version": ALIGNED_FINAL_CONTRACT_VERSION,
            "output_key": output_key,
            "aligned_packet_key": packet["packet_key"],
            "router_output_key": row["router_output"]["output_key"],
            "proposition_check": {
                "model_id": row["victim_model_id"],
                "cache_key": check["cache_key"],
                "proposition": check["proposition"],
                "judgment": check["judgment"],
            },
            "final_selector": {
                "model_id": row["victim_model_id"],
                "cache_key": receipts[-1]["cache_key"],
                "judgment": judgment,
            },
            "derived_prediction": prediction,
        }
        path, cached = store_immutable_output(output_root, output_key, output)
        return {
            "output_key": output_key,
            "output_path": str(path),
            "proposition_cache_key": check["cache_key"],
            "final_cache_key": receipts[-1]["cache_key"],
            "final_cache_hit": receipts[-1]["cache_hit"],
            "cached_output": cached,
            "selected_endpoint": judgment["selected_endpoint"],
            "prediction": prediction,
        }

    eligible_rows = [row for row in rows if row["packet"]["packet_key"] in checks]
    ledger.update(
        status="running" if not failures else "failed",
        phase="final_selector",
        event="aligned_final_started",
        counts={"disagreements": len(rows), "checks": len(checks), "finals": 0, "failed": len(failures)},
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_rows = {executor.submit(final_job, row): row for row in eligible_rows}
        for completed, future in enumerate(concurrent.futures.as_completed(future_rows), 1):
            row = future_rows[future]
            try:
                result = future.result()
                outputs.append(
                    {
                        "claim_id": row["claim_id"],
                        "victim_model_id": row["victim_model_id"],
                        "condition_id": row["condition_id"],
                        "variant": args.variant,
                        "aligned_packet_key": row["packet"]["packet_key"],
                        "aligned_packet_path": row["aligned_packet_path"],
                        "router_output_key": row["router_output"]["output_key"],
                        "router_output_path": row["output_path"],
                        **result,
                    }
                )
                print(
                    f"final {completed}/{len(eligible_rows)} model={row['victim_model_id']} "
                    f"claim={row['claim_id']} condition={row['condition_id']} "
                    f"endpoint={result['selected_endpoint']} cached={result['final_cache_hit']}"
                )
            except Exception as exc:
                failures.append(
                    {
                        "phase": "final_selector",
                        "claim_id": row["claim_id"],
                        "model_id": row["victim_model_id"],
                        "condition_id": row["condition_id"],
                        "error": repr(exc),
                        "traceback": traceback.format_exc(),
                    }
                )
                print(f"final {completed}/{len(eligible_rows)} FAILED claim={row['claim_id']}: {exc}")
            if completed % 10 == 0 or completed == len(eligible_rows):
                ledger.update(
                    status="running" if not failures else "failed",
                    phase="final_selector",
                    event="aligned_final_progress",
                    counts={"disagreements": len(rows), "checks": len(checks), "finals": len(outputs), "failed": len(failures)},
                )

    outputs.sort(key=lambda row: (row["claim_id"], row["victim_model_id"], row["condition_id"]))
    manifest_path = run_root / "private_manifest.json"
    atomic_json(
        manifest_path,
        {
            "warning": "PRIVATE METADATA: never serialize condition/model fields into prompts",
            "experiment_id": args.experiment_id,
            "router_experiment_id": manifest["experiment_id"],
            "variant": args.variant,
            "conditions": sorted(conditions),
            "models": sorted(requested_models),
            "target_disagreements": len(rows),
            "checks_completed": len(checks),
            "finals_expected": len(eligible_rows),
            "outputs": outputs,
            "failures": failures,
        },
    )
    status = "complete" if not failures and len(outputs) == len(rows) else "failed"
    ledger.update(
        status=status,
        phase="final_selector",
        event="aligned_verification_completed" if status == "complete" else "aligned_verification_failed",
        counts={"disagreements": len(rows), "checks": len(checks), "finals": len(outputs), "failed": len(failures)},
        artifacts={"manifest": str(manifest_path)},
    )
    print(json.dumps({"status": status, "disagreements": len(rows), "outputs": len(outputs), "failures": len(failures)}, indent=2))
    if status != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
