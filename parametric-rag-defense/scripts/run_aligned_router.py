#!/usr/bin/env python3
"""Run exact same-model endpoint-only/evidence-aware LLM routers."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

from parametric_rag_defense.aligned_workflow import (
    ALIGNED_ROUTER_CONTRACT_VERSION,
    build_aligned_packet,
    parse_aligned_router_text,
    selected_prediction,
)
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import LLMCache, LLMRequest, canonical_json
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.workflow_runtime import (
    execute_cached,
    prompt_version,
    render,
    store_immutable_output,
)

VARIANT_PROMPTS = {
    "endpoint_only": Path("prompts/aligned_router_endpoint_v1.md"),
    "evidence_aware": Path("prompts/aligned_router_evidence_v1.md"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1-config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--stage2-root", type=Path, default=Path("artifacts/runs/stage2/stage2_signal_v1")
    )
    parser.add_argument("--experiment-id", default="stage3_same_model_ab_v1")
    parser.add_argument("--conditions", default="clean,fact2fiction_p0.01")
    parser.add_argument("--variants", default="endpoint_only,evidence_aware")
    parser.add_argument("--models", help="Optional comma-separated model-ID subset")
    parser.add_argument("--claims", help="Optional comma-separated claim-ID subset")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--contract-retries", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.workers < 1 or args.contract_retries < 0:
        raise SystemExit("workers must be positive and contract retries nonnegative")

    config_path = args.stage1_config.resolve()
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
        raise SystemExit(f"Unknown or ineligible same-model configurations: {sorted(missing_models)}")
    conditions = set(args.conditions.split(","))
    variants = args.variants.split(",")
    unknown_variants = set(variants) - set(VARIANT_PROMPTS)
    if unknown_variants:
        raise SystemExit(f"Unknown variants: {sorted(unknown_variants)}")
    selected_claims = set(int(value) for value in args.claims.split(",")) if args.claims else None

    index = json.loads((args.stage2_root / "private_index.json").read_text(encoding="utf-8"))
    rows = [
        row
        for row in index["rows"]
        if row["victim_model_id"] in requested_models
        and row["condition_id"] in conditions
        and (selected_claims is None or int(row["claim_id"]) in selected_claims)
    ]
    rows.sort(key=lambda row: (row["claim_id"], row["victim_model_id"], row["condition_id"]))
    if not rows:
        raise SystemExit("No Stage 2 rows match the requested aligned scope")

    namespace = config["rag_pipeline"]["artifact_namespace"]
    rag_root = Path("artifacts/runs/stage1/development/rag") / namespace / "endpoints"
    run_root = Path("artifacts/runs/stage3") / args.experiment_id
    packet_root = run_root / "packets"
    output_root = run_root / "outputs"
    cache = LLMCache(Path(config["cache_root"]).resolve())
    ledger = ExperimentLedger(
        Path("artifacts/runs/progress"),
        args.experiment_id,
        description="Strict same-model endpoint and evidence router A/B experiment",
    )
    expected = len(rows) * len(variants)
    ledger.update(
        status="running",
        phase="packet_build",
        event="aligned_router_started",
        counts={"source_rows": len(rows), "expected": expected, "completed": 0, "failed": 0},
        details={"conditions": sorted(conditions), "models": sorted(requested_models), "variants": variants},
    )

    templates: dict[str, tuple[str, str]] = {
        variant: prompt_version(VARIANT_PROMPTS[variant], f"aligned_router_{variant}_v1")
        for variant in variants
    }
    prepared: list[dict[str, Any]] = []
    packet_cache_hits = 0
    for row in rows:
        source_packet = json.loads(Path(row["packet_path"]).read_text(encoding="utf-8"))
        endpoint_path = rag_root / row["rag_task_key"][:2] / f"{row['rag_task_key']}.json"
        endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
        if endpoint["task_key"] != row["rag_task_key"]:
            raise ValueError(f"RAG task-key mismatch: {endpoint_path}")
        if endpoint["task"]["model_id"] != row["victim_model_id"]:
            raise ValueError(f"RAG victim mismatch: {endpoint_path}")
        for variant in variants:
            packet = build_aligned_packet(
                source_packet=source_packet,
                rag_judgment=endpoint["judgment"],
                model_id=row["victim_model_id"],
                variant=variant,
            )
            packet_path, packet_cached = store_immutable_output(
                packet_root / variant, packet["packet_key"], packet
            )
            packet_cache_hits += int(packet_cached)
            prepared.append({**row, "variant": variant, "aligned_packet": packet, "aligned_packet_path": str(packet_path)})

    decoding = {
        "temperature": 0.2,
        "top_p": 0.7,
        "max_tokens": 1200,
        "seed": 11,
    }
    outputs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    def job(item: dict[str, Any]) -> dict[str, Any]:
        model = models[item["victim_model_id"]]
        packet = item["aligned_packet"]
        template, version = templates[item["variant"]]
        prompt = render(
            template,
            {
                "ALIGNED_PACKET": json.dumps(
                    packet["visible"], ensure_ascii=False, sort_keys=True, indent=2
                )
            },
        )
        request = LLMRequest(
            stage="stage3_aligned_router",
            provider=model["provider"],
            model=model["model"],
            prompt_id=f"aligned_router_{item['variant']}",
            prompt_version=version,
            messages=[{"role": "user", "content": prompt}],
            parameters={**decoding, **model.get("request_parameters", {})},
            response_format={"type": "json_object"},
        )
        if args.dry_run:
            return {
                "cache_key": request.key,
                "cache_hit": False,
                "dry_run": True,
                "judgment": None,
                "prediction": None,
                "output_key": None,
                "output_path": None,
                "cached_output": False,
            }
        judgment, receipts = execute_cached(
            cache=cache,
            request=request,
            parser=parse_aligned_router_text,
            metadata={
                "role": "aligned_same_model_router",
                "aligned_packet_key": packet["packet_key"],
                "model_id": item["victim_model_id"],
                "variant": item["variant"],
            },
            contract_name="aligned router contract",
            retries=args.contract_retries,
        )
        prediction = selected_prediction(packet, judgment["provisional_endpoint"])
        output_key = hashlib.sha256(
            canonical_json(
                {
                    "aligned_packet_key": packet["packet_key"],
                    "router_cache_key": receipts[-1]["cache_key"],
                    "contract_version": ALIGNED_ROUTER_CONTRACT_VERSION,
                }
            ).encode()
        ).hexdigest()
        output = {
            "output_schema_version": 1,
            "contract_version": ALIGNED_ROUTER_CONTRACT_VERSION,
            "output_key": output_key,
            "aligned_packet_key": packet["packet_key"],
            "router": {
                "cache_key": receipts[-1]["cache_key"],
                "model_id": item["victim_model_id"],
                "variant": item["variant"],
                "judgment": judgment,
            },
            "derived_prediction": prediction,
        }
        output_path, cached_output = store_immutable_output(output_root, output_key, output)
        return {
            "cache_key": receipts[-1]["cache_key"],
            "cache_hit": receipts[-1]["cache_hit"],
            "dry_run": False,
            "judgment": judgment,
            "prediction": prediction,
            "output_key": output_key,
            "output_path": str(output_path),
            "cached_output": cached_output,
        }

    ledger.update(
        status="running",
        phase="router_calls",
        event="aligned_packets_built",
        counts={"source_rows": len(rows), "expected": expected, "completed": 0, "failed": 0},
        details={"packet_cache_hits": packet_cache_hits},
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_items = {executor.submit(job, item): item for item in prepared}
        for completed, future in enumerate(concurrent.futures.as_completed(future_items), 1):
            item = future_items[future]
            try:
                result = future.result()
                outputs.append(
                    {
                        **{key: value for key, value in item.items() if key != "aligned_packet"},
                        **result,
                    }
                )
                route = result["judgment"]["route"] if result["judgment"] else "dry_run"
                print(
                    f"router {completed}/{expected} model={item['victim_model_id']} "
                    f"claim={item['claim_id']} condition={item['condition_id']} "
                    f"variant={item['variant']} route={route} cached={result['cache_hit']}"
                )
            except Exception as exc:
                failures.append(
                    {
                        "claim_id": item["claim_id"],
                        "victim_model_id": item["victim_model_id"],
                        "condition_id": item["condition_id"],
                        "variant": item["variant"],
                        "error": repr(exc),
                        "traceback": traceback.format_exc(),
                    }
                )
                print(
                    f"router {completed}/{expected} FAILED model={item['victim_model_id']} "
                    f"claim={item['claim_id']} variant={item['variant']}: {exc}"
                )
            if completed % 10 == 0 or completed == expected:
                ledger.update(
                    status="running" if not failures else "failed",
                    phase="router_calls",
                    event="aligned_router_progress",
                    counts={
                        "source_rows": len(rows),
                        "expected": expected,
                        "completed": len(outputs),
                        "failed": len(failures),
                    },
                )

    outputs.sort(
        key=lambda row: (
            row["claim_id"], row["victim_model_id"], row["condition_id"], row["variant"]
        )
    )
    variant_counts = Counter(row["variant"] for row in outputs)
    model_counts = Counter(row["victim_model_id"] for row in outputs)
    manifest_path = run_root / "private_manifest.json"
    atomic_json(
        manifest_path,
        {
            "warning": "PRIVATE METADATA: never serialize condition/model fields into prompts",
            "experiment_id": args.experiment_id,
            "dry_run": args.dry_run,
            "conditions": sorted(conditions),
            "variants": variants,
            "models": sorted(requested_models),
            "source_rows": len(rows),
            "expected_outputs": expected,
            "variant_counts": dict(sorted(variant_counts.items())),
            "model_counts": dict(sorted(model_counts.items())),
            "outputs": outputs,
            "failures": failures,
        },
    )
    status = "complete" if len(outputs) == expected and not failures else "failed"
    ledger.update(
        status=status,
        phase="router_calls",
        event="aligned_router_completed" if status == "complete" else "aligned_router_failed",
        counts={
            "source_rows": len(rows),
            "expected": expected,
            "completed": len(outputs),
            "failed": len(failures),
        },
        artifacts={"manifest": str(manifest_path)},
    )
    print(json.dumps({"status": status, "outputs": len(outputs), "failures": len(failures)}, indent=2))
    if status != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
