#!/usr/bin/env python3
"""Run matched and stress-aware same-model endpoint selectors."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any

from build_stage2_packets import internal_lookup
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import LLMCache, LLMRequest, canonical_json
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.rag_stress_arbiter import (
    STRESS_ARBITER_CONTRACT_VERSION,
    build_stress_arbiter_packet,
    champion_prediction,
    parse_stress_arbiter_text,
)
from parametric_rag_defense.workflow_runtime import (
    execute_cached,
    prompt_version,
    render,
    store_immutable_output,
)


def identity(row: dict[str, Any]) -> tuple[str, int, str]:
    return row["victim_model_id"], int(row["claim_id"]), row["condition_id"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--protocol", type=Path, default=Path("configs/rag_stress_arbiter_v1.json")
    )
    parser.add_argument(
        "--source-root", type=Path,
        default=Path("artifacts/runs/evidence_signal/evidence_signal_v1"),
    )
    parser.add_argument(
        "--counter-root", type=Path,
        default=Path("artifacts/runs/counter_retrieval/counter_retrieval_signal_v2"),
    )
    parser.add_argument(
        "--stress-root", type=Path,
        default=Path("artifacts/runs/rag_stress/rag_cluster_stress_v1"),
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        raise SystemExit("workers must be positive")

    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    source = json.loads((args.source_root / "private_manifest.json").read_text())
    counter = json.loads((args.counter_root / "private_manifest.json").read_text())
    stress = json.loads((args.stress_root / "private_manifest.json").read_text())
    if source.get("failures") or counter.get("failures") or stress.get("failures"):
        raise ValueError("At least one source manifest has unresolved failures")
    if stress.get("completed_execution_cases") != stress.get("unique_execution_cases"):
        raise ValueError("Stress execution is incomplete")
    if stress.get("completed_named_views") != stress.get("named_views"):
        raise ValueError("Stress named-view coverage is incomplete")
    source_by_id = {identity(row): row for row in source["rows"]}
    counter_by_id = {identity(row): row for row in counter["rows"]}
    if set(source_by_id) != set(counter_by_id):
        raise ValueError("Source and counter scopes differ")
    views_by_id: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for descriptor in stress["views"]:
        output = json.loads(Path(descriptor["output_path"]).read_text())
        answers = output["answers"]["answers"]
        views_by_id[identity(descriptor)].append(
            {
                **descriptor,
                "verdict": output["verdict"]["verdict"],
                "confidence": output["verdict"]["confidence"],
                "answered_count": sum(item["status"] == "answered" for item in answers),
                "question_count": len(answers),
            }
        )
    samples, _ = internal_lookup(
        config,
        Path("artifacts/runs/stage1/development/internal_endpoint"),
        Path(config["cache_root"]),
    )

    rows = []
    failures = []
    for row_id, descriptor in sorted(source_by_id.items(), key=lambda item: item[0]):
        if descriptor["memory_prediction"] not in {"Supported", "Refuted"}:
            continue
        try:
            counter_descriptor = counter_by_id[row_id]
            source_packet = json.loads(Path(descriptor["packet_path"]).read_text())
            endpoint = json.loads(Path(descriptor["endpoint_path"]).read_text())
            counter_output = json.loads(Path(counter_descriptor["output_path"]).read_text())
            counter_loose = counter_output["judgment"]["overall_assessment"]["direction"]
            counter_label = {
                "supports": "Supported",
                "refutes": "Refuted",
            }.get(counter_loose)
            champion_row = {
                "counter_loose_label": counter_label or "Not Enough Evidence",
                "rag_prediction": descriptor["retrieval_prediction"],
                "memory_prediction": descriptor["memory_prediction"],
                "cascade_prediction": descriptor["memory_prediction"],
            }
            champion = champion_prediction(champion_row)
            questions = endpoint["judgment"]["questions"]
            for variant in ("control", "full"):
                packet = build_stress_arbiter_packet(
                    variant=variant,
                    claim=source_packet["visible"]["claim"],
                    claim_date=source_packet["visible"]["claim_date"],
                    neutral_claim_plan=source_packet["visible"]["neutral_claim_plan"],
                    rag_prediction=descriptor["retrieval_prediction"],
                    memory_prediction=descriptor["memory_prediction"],
                    champion=champion,
                    internal_samples=samples[row_id[0]][row_id[1]],
                    original_rag_confidence=endpoint["judgment"]["confidence"],
                    original_answered_count=sum(
                        item["status"] == "answered" for item in questions
                    ),
                    original_question_count=len(questions),
                    stress_views=views_by_id[row_id],
                )
                rows.append(
                    {
                        "variant": variant,
                        "victim_model_id": row_id[0],
                        "claim_id": row_id[1],
                        "condition_id": row_id[2],
                        "rag_prediction": descriptor["retrieval_prediction"],
                        "memory_prediction": descriptor["memory_prediction"],
                        "champion_prediction": champion,
                        "rag_task_key": descriptor["rag_task_key"],
                        "packet": packet,
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

    run_root = Path("artifacts/runs/rag_stress_arbiter") / protocol["experiment_id"]
    packet_root = run_root / "packets"
    output_root = run_root / "outputs"
    manifest_rows = []
    for row in rows:
        path, cached = store_immutable_output(
            packet_root, row["packet"]["packet_key"], row["packet"]
        )
        manifest_rows.append(
            {
                **{key: value for key, value in row.items() if key != "packet"},
                "packet_key": row["packet"]["packet_key"],
                "packet_path": str(path),
                "packet_cached": cached,
            }
        )
    expected = protocol["call_budget"]["total_before_contract_repairs"]
    preflight = {
        "manifest_schema_version": 1,
        "experiment_id": protocol["experiment_id"],
        "expected_outputs": expected,
        "packet_outputs": len(manifest_rows),
        "binary_endpoint_rows": len(manifest_rows) // 2,
        "variants": ["control", "full"],
        "failures": failures,
        "rows": manifest_rows,
    }
    atomic_json(run_root / "private_manifest.json", preflight)
    if failures or len(manifest_rows) != expected:
        raise SystemExit(1)
    if args.prepare_only:
        print(
            json.dumps(
                {key: value for key, value in preflight.items() if key != "rows"},
                indent=2,
            )
        )
        return

    load_dotenv(config_path.parent.parent / ".env")
    models = {model["id"]: model for model in config["models"] if model.get("enabled")}
    template, version = prompt_version(
        Path("prompts/rag_stress_arbiter_v1.md"), "rag_stress_arbiter_v1"
    )
    cache = LLMCache(Path(config["cache_root"]).resolve())
    decoding = protocol["decoding"]
    ledger = ExperimentLedger(
        Path("artifacts/runs/progress"), protocol["experiment_id"],
        description="Matched and stress-aware same-model endpoint selectors",
    )

    def run_one(row: dict[str, Any]) -> dict[str, Any]:
        packet = json.loads(Path(row["packet_path"]).read_text())
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
            stage="rag_stress_arbiter_v1",
            provider=model["provider"], model=model["model"],
            prompt_id="rag_stress_arbiter", prompt_version=version,
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
        judgment, receipts = execute_cached(
            cache=cache, request=request, parser=parse_stress_arbiter_text,
            metadata={
                "role": f"same_model_rag_stress_arbiter_{row['variant']}",
                "packet_key": packet["packet_key"],
                "model_id": row["victim_model_id"],
            },
            contract_name=STRESS_ARBITER_CONTRACT_VERSION,
            retries=decoding["contract_retries"],
        )
        output_key = hashlib.sha256(
            canonical_json(
                {
                    "packet_key": packet["packet_key"],
                    "arbiter_cache_key": receipts[-1]["cache_key"],
                    "contract_version": STRESS_ARBITER_CONTRACT_VERSION,
                }
            ).encode()
        ).hexdigest()
        output = {
            "output_schema_version": 1,
            "contract_version": STRESS_ARBITER_CONTRACT_VERSION,
            "output_key": output_key,
            "packet_key": packet["packet_key"],
            "arbiter_cache_key": receipts[-1]["cache_key"],
            "judgment": judgment,
        }
        path, cached_output = store_immutable_output(output_root, output_key, output)
        return {
            "output_key": output_key,
            "output_path": str(path),
            "arbiter_cache_key": receipts[-1]["cache_key"],
            "cache_hit": receipts[-1]["cache_hit"],
            "cached_output": cached_output,
            "receipts": receipts,
        }

    ledger.update(
        status="running", phase="arbiter", event="arbiter_started",
        counts={"expected": len(manifest_rows), "completed": 0, "failed": 0},
    )
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(run_one, row): (
                row["variant"], row["victim_model_id"], row["claim_id"], row["condition_id"]
            )
            for row in manifest_rows
        }
        for count, future in enumerate(concurrent.futures.as_completed(futures), 1):
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
            if count % 10 == 0 or count == len(futures):
                print(f"arbiter {count}/{len(futures)} failures={len(failures)}")
                ledger.update(
                    status="failed" if failures else "running", phase="arbiter",
                    event="arbiter_progress",
                    counts={"expected": len(futures), "completed": len(results), "failed": len(failures)},
                )
    final_rows = []
    for row in manifest_rows:
        row_id = (row["variant"], row["victim_model_id"], row["claim_id"], row["condition_id"])
        if row_id in results:
            final_rows.append({**row, **results[row_id]})
    manifest = {
        **preflight,
        "completed_outputs": len(final_rows),
        "contract_version": STRESS_ARBITER_CONTRACT_VERSION,
        "rows": final_rows,
        "failures": failures,
    }
    atomic_json(run_root / "private_manifest.json", manifest)
    status = "complete" if not failures and len(final_rows) == expected else "failed"
    ledger.update(
        status=status, phase="arbiter",
        event="arbiter_completed" if status == "complete" else "arbiter_failed",
        counts={"expected": expected, "completed": len(final_rows), "failed": len(failures)},
        artifacts={"manifest": str(run_root / "private_manifest.json")},
    )
    print(json.dumps({"status": status, "outputs": len(final_rows), "failures": len(failures)}, indent=2))
    if status != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
