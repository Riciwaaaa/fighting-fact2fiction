#!/usr/bin/env python3
"""Audit scope, reuse, cache, and output contracts for the top-10 RAG diagnostic."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json


def identity(endpoint: dict[str, Any]) -> tuple[str, int, str]:
    task = endpoint["task"]
    return task["model_id"], int(task["claim_id"]), task["condition"]["id"]


def load_by_identity(root: Path) -> dict[tuple[str, int, str], dict[str, Any]]:
    result = {}
    for path in root.glob("*/*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        key = identity(value)
        if key in result:
            raise ValueError(f"duplicate endpoint: {key}")
        result[key] = value
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/rag_top10_confirmation_diagnostic_v1.json"),
    )
    parser.add_argument(
        "--source-results",
        type=Path,
        default=Path(
            "artifacts/evaluation/environment_confirmation_train_v1/"
            "environment_conditioned_results.json"
        ),
    )
    parser.add_argument(
        "--source-endpoints",
        type=Path,
        default=Path(
            "artifacts/runs/environment_confirmation_train_v1/stage1/confirmation/rag/"
            "stage1_train_confirmation_v1/endpoints"
        ),
    )
    parser.add_argument(
        "--source-traces",
        type=Path,
        default=Path(
            "artifacts/runs/environment_confirmation_train_v1/stage1/confirmation/rag/"
            "stage1_train_confirmation_v1/private_traces"
        ),
    )
    parser.add_argument(
        "--top10-root",
        type=Path,
        default=Path(
            "artifacts/runs/rag_top10_confirmation_v1/stage1/confirmation/rag/"
            "rag_top10_confirmation_v1"
        ),
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path("artifacts/cache/llm_rag_top10_confirmation_v1"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluation/rag_top10_confirmation_v1/audit.json"),
    )
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    source_results = json.loads(args.source_results.read_text(encoding="utf-8"))
    expected = {
        (row["victim_model_id"], int(row["claim_id"]), row["condition_id"])
        for row in source_results["private_rows"]
    }
    source = load_by_identity(args.source_endpoints)
    source_traces = load_by_identity(args.source_traces)
    top10 = load_by_identity(args.top10_root / "endpoints")
    traces = load_by_identity(args.top10_root / "private_traces")
    failures: list[dict[str, Any]] = []
    stage_counts: dict[str, int] = {}
    cache_keys = set()

    for key in sorted(expected & set(top10)):
        endpoint = top10[key]
        source_endpoint = source[key]
        trace = traces.get(key)
        if trace is None:
            failures.append({"identity": key, "failure": "missing_trace"})
            continue
        source_trace = source_traces.get(key)
        if source_trace is None:
            failures.append({"identity": key, "failure": "missing_source_trace"})
            continue
        if trace["task_key"] != endpoint["task_key"]:
            failures.append({"identity": key, "failure": "endpoint_trace_key_mismatch"})
        if trace.get("plan") != source_trace.get("plan"):
            failures.append({"identity": key, "failure": "source_question_plan_mismatch"})
        source_plan_keys = [
            receipt["cache_key"] for receipt in source_trace["llm_receipts"]["plan"]
        ]
        top10_plan_receipts = trace["llm_receipts"]["plan"]
        if [receipt["cache_key"] for receipt in top10_plan_receipts] != source_plan_keys:
            failures.append({"identity": key, "failure": "source_plan_receipt_mismatch"})
        if not all(
            receipt.get("reused_from_original_top5_trace")
            for receipt in top10_plan_receipts
        ):
            failures.append({"identity": key, "failure": "source_plan_reuse_unmarked"})
        if endpoint["provenance"].get("retrieval_top_k") != 10:
            failures.append({"identity": key, "failure": "wrong_top_k"})
        if endpoint["task"].get("rag_pipeline_version") != config["rag_pipeline"]["version"]:
            failures.append({"identity": key, "failure": "pipeline_version_mismatch"})
        if endpoint["audit"]["poison_documents_injected"] != source_endpoint["audit"][
            "poison_documents_injected"
        ]:
            failures.append({"identity": key, "failure": "poison_budget_mismatch"})
        for stage in ("answers", "verdict"):
            receipts = trace["llm_receipts"][stage]
            if not receipts or not receipts[-1].get("contract_ok"):
                failures.append({"identity": key, "failure": f"{stage}_contract"})
            for receipt in receipts:
                cache_key = receipt["cache_key"]
                cache_keys.add(cache_key)
                path = args.cache_root / "entries" / cache_key[:2] / f"{cache_key}.json"
                if not path.exists():
                    failures.append({"identity": key, "failure": f"missing_{stage}_cache"})
                    continue
                entry = json.loads(path.read_text(encoding="utf-8"))
                request_stage = entry["request"]["stage"]
                stage_counts[request_stage] = stage_counts.get(request_stage, 0) + 1
                if entry.get("key") != cache_key:
                    failures.append({"identity": key, "failure": "cache_key_mismatch"})
        if key[2] == "clean" and endpoint["audit"]["retrieved_poison_documents"] != 0:
            failures.append({"identity": key, "failure": "clean_poison_exposure"})

    poison_manifest = json.loads(
        (args.top10_root / "manifests" / "top10_poison_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    result = {
        "audit_schema_version": 1,
        "experiment_id": "rag_top10_confirmation_v1",
        "status": "passed" if not failures else "failed",
        "scope": {
            "expected": len(expected),
            "endpoints": len(top10),
            "traces": len(traces),
            "missing": len(expected - set(top10)),
            "unexpected": len(set(top10) - expected),
            "trace_missing": len(expected - set(traces)),
            "trace_unexpected": len(set(traces) - expected),
        },
        "configuration": {
            "frozen": config.get("status")
            == "frozen_before_rag_top10_diagnostic_inference",
            "retrieval_top_k": config["rag_pipeline"]["retrieval_top_k"],
            "closed_book_inference": False,
            "source_questions_reused": True,
            "source_poison_corpora_reused": True,
            "source_top5_eligibility_reused": True,
        },
        "manifest": {
            "requested": poison_manifest["requested"],
            "successes": len(poison_manifest["successes"]),
            "failures": len(poison_manifest["failures"]),
        },
        "cache": {
            "referenced_answer_or_verdict_keys": len(cache_keys),
            "request_stage_receipts": stage_counts,
        },
        "failures": failures,
    }
    if any(
        result["scope"][field]
        for field in ("missing", "unexpected", "trace_missing", "trace_unexpected")
    ):
        result["status"] = "failed"
    if result["manifest"]["successes"] != 1260 or result["manifest"]["failures"]:
        result["status"] = "failed"
    atomic_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "passed":
        raise SystemExit("top-10 diagnostic audit failed")


if __name__ == "__main__":
    main()
