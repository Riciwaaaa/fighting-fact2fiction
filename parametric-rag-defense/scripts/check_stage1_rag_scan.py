#!/usr/bin/env python3
"""Verify completeness and cache provenance for a configured Stage 1 RAG rate scan."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json, poison_document_count
from parametric_rag_defense.cache import canonical_json
from parametric_rag_defense.matrix import build_rag_tasks, select_tier_conditions
from parametric_rag_defense.rag_artifacts import artifact_path, normalize_record

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    import numpy as np

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument("--tier", default="development_sweep")
    parser.add_argument(
        "--allow-out-of-scope",
        action="store_true",
        help="permit other content-addressed endpoints in the shared namespace",
    )
    parser.add_argument("--data-root", type=Path, default=Path("artifacts/data/averitec"))
    parser.add_argument("--eligibility", type=Path)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    split = json.loads(Path(config["dataset"]["split_manifest"]).read_text(encoding="utf-8"))
    claim_ids = split["development"]["claim_ids"]
    enabled = {
        model["id"] for model in config["models"]
        if model.get("enabled", True) and "rag_victim" in model["roles"]
    }
    selected_conditions = select_tier_conditions(config, args.tier)
    rates = tuple(
        float(condition["strength"])
        for condition in selected_conditions
        if condition["attack_family"] == "fact2fiction"
    )
    if not rates:
        raise SystemExit(f"tier {args.tier!r} contains no Fact2Fiction rates")
    tasks = {
        (task["model_id"], task["claim_id"], task["condition"]["id"]): task
        for task in build_rag_tasks(config, args.tier, claim_ids)
        if task["model_id"] in enabled
    }
    namespace = config["rag_pipeline"]["artifact_namespace"]
    run_root = Path(config["run_root"]) / "development" / "rag" / namespace
    endpoint_root = run_root / "endpoints"
    trace_root = run_root / "private_traces"
    cache_root = Path(config["cache_root"]) / "entries"
    eligibility_path = args.eligibility or Path(
        f"artifacts/evaluation/{namespace}_clean_eligibility.json"
    )
    output_path = args.output or run_root / "audit.json"
    if not eligibility_path.exists():
        raise SystemExit(f"missing eligibility file: {eligibility_path}")
    eligibility = json.loads(eligibility_path.read_text(encoding="utf-8"))

    expected_keys: set[str] = set()
    clean_expected = len(enabled) * len(claim_ids)
    attacked_expected = 0
    for model_id in enabled:
        expected_keys.update(tasks[(model_id, claim_id, "clean")]["task_key"] for claim_id in claim_ids)
        eligible = eligibility["models"][model_id]["eligible_claim_ids"]
        attacked_expected += len(eligible) * len(rates)
        for claim_id in eligible:
            expected_keys.update(
                tasks[(model_id, claim_id, f"fact2fiction_p{rate:g}")]["task_key"]
                for rate in rates
            )

    active_endpoint_keys = {path.stem for path in endpoint_root.glob("*/*.json")}
    active_trace_keys = {path.stem for path in trace_root.glob("*/*.json")}
    unexpected_endpoint_keys = sorted(active_endpoint_keys - expected_keys)
    unexpected_trace_keys = sorted(active_trace_keys - expected_keys)

    missing = []
    failures = []
    cache_keys: set[str] = set()
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    condition_counts: dict[str, int] = {}
    for key in sorted(expected_keys):
        path = artifact_path(endpoint_root, key)
        if not path.exists():
            missing.append(key)
            continue
        artifact = json.loads(path.read_text(encoding="utf-8"))
        task = artifact["task"]
        record = {
            "task_key": artifact["task_key"],
            "judgment": artifact["judgment"],
            "audit": artifact["audit"],
            "provenance": artifact["provenance"],
        }
        if normalize_record(record, task) != artifact:
            failures.append(f"noncanonical artifact {key}")
        judgment_text = json.dumps(artifact["judgment"], ensure_ascii=False)
        if re.search(r"\b(?:clean|poison):\d+\b", judgment_text, flags=re.IGNORECASE):
            failures.append(f"source-origin identifier in normalized judgment {key}")
        trace = trace_root / key[:2] / f"{key}.json"
        if not trace.exists():
            failures.append(f"missing trace {key}")
        condition = task["condition"]["id"]
        condition_counts[condition] = condition_counts.get(condition, 0) + 1
        clean_count = artifact["audit"]["clean_documents_before_injection"]
        if condition != "clean":
            expected_injected = poison_document_count(clean_count, float(task["condition"]["strength"]))
            if artifact["audit"]["poison_documents_injected"] != expected_injected:
                failures.append(f"wrong poison count {key}")
        for keys in artifact["provenance"]["llm_cache_keys"].values():
            cache_keys.update(keys)

    poison_material_failures = []
    victim_prompt_failures = []
    for model_id in enabled:
        for claim_id in eligibility["models"][model_id]["eligible_claim_ids"]:
            path = run_root / "poison_corpora" / model_id / f"{claim_id}.json"
            embeddings = path.with_suffix(".npy")
            if not path.exists() or not embeddings.exists():
                poison_material_failures.append(f"missing poison material {model_id}/{claim_id}")
                continue
            material = json.loads(path.read_text(encoding="utf-8"))
            required = poison_document_count(material["clean_document_count"], max(rates))
            if len(material["documents"]) < required or material["maximum_poison_count"] < required:
                poison_material_failures.append(f"insufficient poison corpus size {model_id}/{claim_id}")
            document_digest = hashlib.sha256(
                json.dumps(
                    material["documents"], sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            if material.get("documents_sha256") != document_digest:
                poison_material_failures.append(f"poison document digest mismatch {model_id}/{claim_id}")
            try:
                embedding_rows = np.load(embeddings, mmap_mode="r").shape[0]
            except (OSError, ValueError) as exc:
                poison_material_failures.append(
                    f"unreadable poison embeddings {model_id}/{claim_id}: {exc!r}"
                )
            else:
                if embedding_rows != len(material["documents"]):
                    poison_material_failures.append(
                        f"poison text/embedding row mismatch {model_id}/{claim_id}"
                    )
            for receipt in material.get("llm_receipts", []):
                cache_keys.add(receipt["cache_key"])

    for key in sorted(cache_keys):
        path = cache_root / key[:2] / f"{key}.json"
        if not path.exists():
            failures.append(f"missing LLM cache entry {key}")
            continue
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry.get("key") != key:
            failures.append(f"cache key mismatch {key}")
        request_digest = hashlib.sha256(canonical_json(entry["request"]).encode("utf-8")).hexdigest()
        if request_digest != key:
            failures.append(f"cache request digest mismatch {key}")
        request = entry["request"]
        if request.get("stage") in {
            "stage1_rag_plan",
            "stage1_rag_answers",
            "stage1_rag_verdict",
        }:
            prompt_text = "\n".join(
                str(message.get("content", "")) for message in request.get("messages", [])
            )
            if re.search(r"\b(?:clean|poison):\d+\b", prompt_text, flags=re.IGNORECASE):
                victim_prompt_failures.append(f"source-origin identifier in victim prompt {key}")
            if re.search(r"https?://", prompt_text, flags=re.IGNORECASE):
                victim_prompt_failures.append(f"raw URL in victim prompt {key}")
        response_usage = entry["response"].get("usage", {})
        for field in usage:
            value = response_usage.get(field)
            if isinstance(value, int):
                usage[field] += value

    index_manifest = args.data_root / "index_manifest.json"
    extraction_manifest = args.data_root / "extraction_manifest.json"
    report: dict[str, Any] = {
        "audit_schema_version": 1,
        "tier": args.tier,
        "rates": list(rates),
        "expected": {
            "clean": clean_expected,
            "attacked": attacked_expected,
            "total": clean_expected + attacked_expected,
        },
        "observed": {
            "complete": len(expected_keys) - len(missing),
            "missing": len(missing),
            "condition_counts": condition_counts,
            "unique_llm_cache_entries_referenced": len(cache_keys),
        },
        "missing_task_keys": missing,
        "unexpected_endpoint_task_keys": unexpected_endpoint_keys,
        "unexpected_trace_task_keys": unexpected_trace_keys,
        "validation_failures": failures,
        "poison_material_failures": poison_material_failures,
        "victim_prompt_failures": victim_prompt_failures,
        "referenced_llm_usage": usage,
        "manifests": {
            "extraction_sha256": sha256(extraction_manifest) if extraction_manifest.exists() else None,
            "index_sha256": sha256(index_manifest) if index_manifest.exists() else None,
            "eligibility_sha256": sha256(eligibility_path),
        },
    }
    atomic_json(output_path.resolve(), report)
    print(json.dumps(report, indent=2, sort_keys=True))
    problems = (
        len(missing)
        + (0 if args.allow_out_of_scope else len(unexpected_endpoint_keys))
        + (0 if args.allow_out_of_scope else len(unexpected_trace_keys))
        + len(failures)
        + len(poison_material_failures)
        + len(victim_prompt_failures)
    )
    if problems and not args.allow_partial:
        raise SystemExit(f"RAG scan audit failed with {problems} problem(s)")


if __name__ == "__main__":
    main()
