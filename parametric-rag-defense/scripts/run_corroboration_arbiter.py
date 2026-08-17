#!/usr/bin/env python3
"""Run a same-model controller over endpoints and two retrieval evidence views."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import traceback
from pathlib import Path
from typing import Any

from build_stage2_packets import internal_lookup
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import LLMCache, LLMRequest, canonical_json
from parametric_rag_defense.corroboration_arbiter import (
    CORROBORATION_ARBITER_CONTRACT_VERSION,
    build_corroboration_packet,
    parse_corroboration_arbiter_text,
)
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.workflow_runtime import (
    execute_cached,
    prompt_version,
    render,
    store_immutable_output,
)


def identity(row: dict[str, Any]) -> tuple[str, int, str]:
    return (
        str(row["victim_model_id"]),
        int(row["claim_id"]),
        str(row["condition_id"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("artifacts/runs/evidence_signal/evidence_signal_v1"),
    )
    parser.add_argument(
        "--counter-root",
        type=Path,
        default=Path("artifacts/runs/counter_retrieval/counter_retrieval_signal_v2"),
    )
    parser.add_argument("--experiment-id", default="corroboration_arbiter_v1")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--contract-retries", type=int, default=2)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1 or args.contract_retries < 0:
        raise SystemExit("workers must be positive and contract retries nonnegative")

    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    source_manifest = json.loads(
        (args.source_root / "private_manifest.json").read_text(encoding="utf-8")
    )
    counter_manifest = json.loads(
        (args.counter_root / "private_manifest.json").read_text(encoding="utf-8")
    )
    counter_audit = json.loads(
        (args.counter_root / "audit.json").read_text(encoding="utf-8")
    )
    if counter_audit.get("status") != "passed" or counter_manifest.get("failures"):
        raise ValueError("Counter-retrieval source is incomplete or unaudited")
    source_by_id = {identity(row): row for row in source_manifest["rows"]}
    if set(source_by_id) != {identity(row) for row in counter_manifest["rows"]}:
        raise ValueError("Source and counter-retrieval scopes differ")
    samples, _ = internal_lookup(
        config,
        Path("artifacts/runs/stage1/development/internal_endpoint"),
        Path(config["cache_root"]),
    )

    run_root = Path("artifacts/runs/corroboration_arbiter") / args.experiment_id
    packet_root = run_root / "packets"
    output_root = run_root / "outputs"
    ledger = ExperimentLedger(
        Path("artifacts/runs/progress"),
        args.experiment_id,
        description="Same-model corroboration-aware endpoint controller",
    )
    rows = []
    failures: list[dict[str, Any]] = []
    for descriptor in counter_manifest["rows"]:
        row_id = identity(descriptor)
        source = source_by_id[row_id]
        try:
            source_packet = json.loads(
                Path(source["packet_path"]).read_text(encoding="utf-8")
            )
            original_output = json.loads(
                Path(source["output_path"]).read_text(encoding="utf-8")
            )
            counter_output = json.loads(
                Path(descriptor["output_path"]).read_text(encoding="utf-8")
            )
            endpoint = json.loads(
                Path(descriptor["endpoint_path"]).read_text(encoding="utf-8")
            )
            model_id, claim_id, condition_id = row_id
            packet = build_corroboration_packet(
                claim=source_packet["visible"]["claim"],
                claim_date=source_packet["visible"]["claim_date"],
                neutral_claim_plan=source_packet["visible"]["neutral_claim_plan"],
                rag_prediction=descriptor["retrieval_prediction"],
                memory_prediction=descriptor["memory_prediction"],
                internal_samples=samples[model_id][claim_id],
                rag_judgment=endpoint["judgment"],
                original_evidence_judgment=original_output["judgment"],
                counter_evidence_judgment=counter_output["judgment"],
                source_packet_key=source_packet["packet_key"],
                counter_packet_key=descriptor["counter_packet_key"],
            )
            packet_path, packet_cached = store_immutable_output(
                packet_root, packet["packet_key"], packet
            )
            rows.append(
                {
                    "victim_model_id": model_id,
                    "claim_id": claim_id,
                    "condition_id": condition_id,
                    "rag_prediction": descriptor["retrieval_prediction"],
                    "memory_prediction": descriptor["memory_prediction"],
                    "source_output_path": source["output_path"],
                    "counter_output_path": descriptor["output_path"],
                    "endpoint_path": descriptor["endpoint_path"],
                    "source_packet_path": source["packet_path"],
                    "counter_packet_path": descriptor["counter_packet_path"],
                    "packet_key": packet["packet_key"],
                    "packet_path": str(packet_path),
                    "packet_cached": packet_cached,
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "phase": "packet",
                    "identity": list(row_id),
                    "error": repr(exc),
                    "traceback": traceback.format_exc(),
                }
            )
    rows.sort(key=lambda row: (row["claim_id"], row["victim_model_id"], row["condition_id"]))
    preflight = {
        "manifest_schema_version": 1,
        "experiment_id": args.experiment_id,
        "expected_rows": len(counter_manifest["rows"]),
        "packet_rows": len(rows),
        "maximum_calls": len(rows),
        "condition_counts": dict(
            sorted(
                {
                    condition: sum(row["condition_id"] == condition for row in rows)
                    for condition in {row["condition_id"] for row in rows}
                }.items()
            )
        ),
        "rows": rows,
        "failures": failures,
    }
    atomic_json(run_root / "private_manifest.json", preflight)
    if failures or len(rows) != len(counter_manifest["rows"]):
        raise SystemExit(1)
    if args.prepare_only:
        print(
            json.dumps(
                {key: value for key, value in preflight.items() if key != "rows"},
                indent=2,
                sort_keys=True,
            )
        )
        return

    load_dotenv(config_path.parent.parent / ".env")
    models = {
        model["id"]: model
        for model in config["models"]
        if model.get("enabled") and "arbiter" in model["roles"]
    }
    template, version = prompt_version(
        Path("prompts/corroboration_arbiter_v1.md"), "corroboration_arbiter_v1"
    )
    cache = LLMCache(Path(config["cache_root"]).resolve())

    def run_one(row: dict[str, Any]) -> dict[str, Any]:
        packet = json.loads(Path(row["packet_path"]).read_text(encoding="utf-8"))
        prompt = render(
            template,
            {
                "ARBITRATION_PACKET": json.dumps(
                    packet["visible"], ensure_ascii=False, sort_keys=True, indent=2
                )
            },
        )
        model = models[row["victim_model_id"]]
        request = LLMRequest(
            stage="corroboration_arbiter_v1",
            provider=model["provider"],
            model=model["model"],
            prompt_id="corroboration_arbiter",
            prompt_version=version,
            messages=[{"role": "user", "content": prompt}],
            parameters={
                "temperature": 0.1,
                "top_p": 0.7,
                "max_tokens": 1800,
                "seed": 433,
                **model.get("request_parameters", {}),
            },
            response_format={"type": "json_object"},
        )
        judgment, receipts = execute_cached(
            cache=cache,
            request=request,
            parser=parse_corroboration_arbiter_text,
            metadata={
                "role": "same_model_corroboration_arbiter",
                "packet_key": packet["packet_key"],
                "model_id": row["victim_model_id"],
            },
            contract_name=CORROBORATION_ARBITER_CONTRACT_VERSION,
            retries=args.contract_retries,
        )
        output_key = hashlib.sha256(
            canonical_json(
                {
                    "packet_key": packet["packet_key"],
                    "arbiter_cache_key": receipts[-1]["cache_key"],
                    "contract_version": CORROBORATION_ARBITER_CONTRACT_VERSION,
                }
            ).encode()
        ).hexdigest()
        output = {
            "output_schema_version": 1,
            "contract_version": CORROBORATION_ARBITER_CONTRACT_VERSION,
            "output_key": output_key,
            "packet_key": packet["packet_key"],
            "arbiter_cache_key": receipts[-1]["cache_key"],
            "judgment": judgment,
        }
        output_path, cached_output = store_immutable_output(
            output_root, output_key, output
        )
        return {
            "output_key": output_key,
            "output_path": str(output_path),
            "arbiter_cache_key": receipts[-1]["cache_key"],
            "cache_hit": receipts[-1]["cache_hit"],
            "cached_output": cached_output,
            "receipts": receipts,
        }

    ledger.update(
        status="running",
        phase="arbiter",
        event="arbiter_started",
        counts={"expected": len(rows), "completed": 0, "failed": 0},
    )
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(run_one, row): identity(row)
            for row in rows
        }
        for completed, future in enumerate(concurrent.futures.as_completed(futures), 1):
            row_id = futures[future]
            try:
                results[row_id] = future.result()
            except Exception as exc:
                failures.append(
                    {
                        "phase": "arbiter",
                        "identity": list(row_id),
                        "error": repr(exc),
                        "traceback": traceback.format_exc(),
                        "receipts": getattr(exc, "receipts", None),
                    }
                )
            if completed % 10 == 0 or completed == len(futures):
                print(f"arbiter {completed}/{len(futures)} failures={len(failures)}")
                ledger.update(
                    status="running" if not failures else "failed",
                    phase="arbiter",
                    event="arbiter_progress",
                    counts={
                        "expected": len(rows),
                        "completed": len(results),
                        "failed": len(failures),
                    },
                )
    final_rows = [
        {**row, **results[identity(row)]}
        for row in rows
        if identity(row) in results
    ]
    final_manifest = {
        **preflight,
        "completed_outputs": len(final_rows),
        "contract_version": CORROBORATION_ARBITER_CONTRACT_VERSION,
        "rows": final_rows,
        "failures": failures,
    }
    atomic_json(run_root / "private_manifest.json", final_manifest)
    status = "complete" if not failures and len(final_rows) == len(rows) else "failed"
    ledger.update(
        status=status,
        phase="arbiter",
        event="arbiter_completed" if status == "complete" else "arbiter_failed",
        counts={
            "expected": len(rows),
            "completed": len(final_rows),
            "failed": len(failures),
        },
        artifacts={"manifest": str(run_root / "private_manifest.json")},
    )
    print(json.dumps({"status": status, "outputs": len(final_rows), "failures": len(failures)}, indent=2))
    if status != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
