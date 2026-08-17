#!/usr/bin/env python3
"""Build a reproducibility and cost ledger for cached Stage 1 internal outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument("--split", help="Split-manifest key; defaults to dataset.active_split")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/runs/stage1/development/internal_endpoint/audit.json"),
    )
    args = parser.parse_args()

    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    args.split = args.split or config["dataset"].get("active_split", "development")
    split_path = Path(config["dataset"]["split_manifest"]).resolve()
    split_manifest = json.loads(split_path.read_text(encoding="utf-8"))
    prompt_path = Path(config["prompt"]["path"]).resolve()
    cache_root = Path(config["cache_root"]).resolve()
    run_root = Path(config["run_root"]).resolve() / args.split / "internal_endpoint"
    expected_claims = set(split_manifest[args.split]["claim_ids"])
    expected_seeds = set(config["decoding"]["internal"]["seeds"])
    expected_pairs = {
        (claim_id, seed) for claim_id in expected_claims for seed in expected_seeds
    }

    report: dict[str, Any] = {
        "audit_schema_version": 1,
        "split": args.split,
        "expected_claims": len(expected_claims),
        "expected_repeats_per_claim": len(expected_seeds),
        "config": {"path": str(config_path), "sha256": sha256_file(config_path)},
        "split_manifest": {"path": str(split_path), "sha256": sha256_file(split_path)},
        "prompt": {"path": str(prompt_path), "sha256": sha256_file(prompt_path)},
        "artifact_tools": {
            "collector": {
                "path": str(Path("scripts/run_stage1_internal.py").resolve()),
                "sha256": sha256_file(Path("scripts/run_stage1_internal.py").resolve()),
            },
            "auditor": {
                "path": str(Path(__file__).resolve()),
                "sha256": sha256_file(Path(__file__).resolve()),
            },
        },
        "models": {},
    }

    for model in config["models"]:
        if "internal" not in model["roles"] or not model.get("enabled", True):
            continue
        manifest_path = run_root / f"{model['id']}.json"
        model_report: dict[str, Any] = {
            "model": model["model"],
            "manifest_path": str(manifest_path),
        }
        if not manifest_path.exists():
            model_report["status"] = "missing_manifest"
            report["models"][model["id"]] = model_report
            continue

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        actual_pairs = {
            (int(row["claim_id"]), int(row["seed"])) for row in manifest.get("outputs", [])
        }
        finish_reasons: Counter[str] = Counter()
        provider_models: Counter[str] = Counter()
        token_usage: Counter[str] = Counter()
        latency_ms: list[float] = []
        created_at: list[str] = []
        corrupt_entries: list[str] = []
        entry_digests: list[str] = []
        contract_failures = 0
        invalid_attempts_retained = 0
        format_retries = 0
        attempted_keys: list[str] = []
        for row in manifest.get("outputs", []):
            if not row.get("contract_ok"):
                contract_failures += 1
            attempts = row.get("attempts") or [
                {
                    "cache_key": row["cache_key"],
                    "contract_ok": row.get("contract_ok"),
                }
            ]
            format_retries += max(0, len(attempts) - 1)
            invalid_attempts_retained += sum(
                not attempt.get("contract_ok") for attempt in attempts
            )
            attempted_keys.extend(str(attempt["cache_key"]) for attempt in attempts)

        for key in dict.fromkeys(attempted_keys):
            entry_path = cache_root / "entries" / key[:2] / f"{key}.json"
            try:
                entry = json.loads(entry_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                corrupt_entries.append(f"{key}: {type(exc).__name__}: {exc}")
                continue
            entry_digests.append(sha256_file(entry_path))
            response = entry["response"]
            finish_reasons[str(response.get("finish_reason"))] += 1
            provider_models[str(response.get("provider_model"))] += 1
            latency = response.get("latency_ms")
            if latency is not None:
                latency_ms.append(float(latency))
            for field, value in response.get("usage", {}).items():
                if isinstance(value, (int, float)):
                    token_usage[field] += value
            if entry.get("created_at"):
                created_at.append(str(entry["created_at"]))

        coverage_ok = actual_pairs == expected_pairs
        complete = (
            coverage_ok
            and not manifest.get("failures")
            and contract_failures == 0
            and not corrupt_entries
        )
        model_report.update(
            {
                "status": "complete" if complete else "incomplete",
                "manifest_sha256": sha256_file(manifest_path),
                "expected_outputs": len(expected_pairs),
                "recorded_outputs": len(actual_pairs),
                "missing_outputs": len(expected_pairs - actual_pairs),
                "extra_outputs": len(actual_pairs - expected_pairs),
                "provider_call_failures": len(manifest.get("failures", [])),
                "contract_failures": contract_failures,
                "format_retries": format_retries,
                "invalid_attempts_retained": invalid_attempts_retained,
                "attempted_cache_entries": len(set(attempted_keys)),
                "corrupt_or_missing_cache_entries": corrupt_entries,
                "attempt_finish_reason_counts": dict(sorted(finish_reasons.items())),
                "attempt_provider_model_counts": dict(sorted(provider_models.items())),
                "attempt_usage": dict(sorted(token_usage.items())),
                "attempt_latency_ms": {
                    "count": len(latency_ms),
                    "mean": statistics.fmean(latency_ms) if latency_ms else None,
                    "median": statistics.median(latency_ms) if latency_ms else None,
                    "p95": percentile(latency_ms, 0.95),
                    "sum": sum(latency_ms),
                },
                "first_cache_record_utc": min(created_at) if created_at else None,
                "last_cache_record_utc": max(created_at) if created_at else None,
                "cache_entry_set_sha256": hashlib.sha256(
                    "\n".join(sorted(entry_digests)).encode("utf-8")
                ).hexdigest(),
            }
        )
        report["models"][model["id"]] = model_report

    report["all_enabled_models_complete"] = all(
        model["status"] == "complete" for model in report["models"].values()
    )
    output = args.output
    if args.split != "development" and output == Path(
        "artifacts/runs/stage1/development/internal_endpoint/audit.json"
    ):
        output = Path(config["run_root"]) / args.split / "internal_endpoint" / "audit.json"
    atomic_json(output.resolve(), report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if not report["all_enabled_models_complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
