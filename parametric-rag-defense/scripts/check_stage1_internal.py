#!/usr/bin/env python3
"""Fail unless Stage 1 internal run manifests and cache entries are complete."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument("--split", help="Split-manifest key; defaults to dataset.active_split")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    args.split = args.split or config["dataset"].get("active_split", "development")
    split = json.loads(Path(config["dataset"]["split_manifest"]).read_text(encoding="utf-8"))
    expected_claims = set(split[args.split]["claim_ids"])
    expected_seeds = set(config["decoding"]["internal"]["seeds"])
    cache_root = Path(config["cache_root"])
    run_root = Path(config["run_root"]) / args.split / "internal_endpoint"
    problems: list[str] = []

    for model in config["models"]:
        if "internal" not in model["roles"] or not model.get("enabled", True):
            continue
        manifest_path = run_root / f"{model['id']}.json"
        if not manifest_path.exists():
            problems.append(f"{model['id']}: missing manifest")
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("dry_run"):
            problems.append(f"{model['id']}: manifest is only a dry run")
        if manifest.get("failures"):
            problems.append(f"{model['id']}: {len(manifest['failures'])} failed calls")
        actual = {(row["claim_id"], row["seed"]) for row in manifest.get("outputs", [])}
        expected = {(claim_id, seed) for claim_id in expected_claims for seed in expected_seeds}
        if actual != expected:
            problems.append(
                f"{model['id']}: output coverage {len(actual)}/{len(expected)}; "
                f"missing={len(expected - actual)} extra={len(actual - expected)}"
            )
        for row in manifest.get("outputs", []):
            if not row.get("contract_ok"):
                problems.append(f"{model['id']}: contract failure claim={row['claim_id']} seed={row['seed']}")
            key = row["cache_key"]
            path = cache_root / "entries" / key[:2] / f"{key}.json"
            if not path.exists():
                problems.append(f"{model['id']}: missing cache entry {key}")
                continue
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
                if entry.get("key") != key:
                    problems.append(f"{model['id']}: key mismatch in {path}")
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(f"{model['id']}: unreadable cache entry {path}: {exc}")

    if problems:
        print("Stage 1 internal completeness FAILED")
        for problem in problems:
            print(f"- {problem}")
        raise SystemExit(1)
    print(
        f"Stage 1 internal completeness passed: split={args.split}, "
        f"models={sum(m.get('enabled', True) and 'internal' in m['roles'] for m in config['models'])}, "
        f"claims={len(expected_claims)}, repeats={len(expected_seeds)}"
    )


if __name__ == "__main__":
    main()
