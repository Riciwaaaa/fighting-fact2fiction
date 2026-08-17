#!/usr/bin/env python3
"""Derive a router manifest for the exact-budget generic end-claim Stage C control.

This makes no model calls. It preserves every aligned packet, endpoint prediction, and router field
except the pivotal proposition, which is replaced by the same generic claim-check text used by the
frozen Stage C fallback. Running ``run_aligned_verification.py`` on the derived manifest therefore
isolates the value of a router-selected proposition at the same two-call budget.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import canonical_json
from parametric_rag_defense.workflow_runtime import store_immutable_output

GENERIC_PROPOSITION = "Whether the original claim's central factual assertion is accurate as stated."
CONTROL_VERSION = "aligned-generic-control-v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--models", default="llama31_70b")
    parser.add_argument("--variants", default="endpoint_only")
    parser.add_argument("--conditions", default="clean,fact2fiction_p0.01")
    args = parser.parse_args()

    source = json.loads((args.source_root / "private_manifest.json").read_text(encoding="utf-8"))
    if source.get("dry_run") or source.get("failures"):
        raise ValueError("Source router manifest is incomplete, dry-run, or failed")
    models = set(args.models.split(","))
    variants = set(args.variants.split(","))
    conditions = set(args.conditions.split(","))
    run_root = Path("artifacts/runs/stage3") / args.experiment_id
    output_root = run_root / "outputs"
    outputs: list[dict[str, Any]] = []
    for descriptor in source["outputs"]:
        if (
            descriptor["victim_model_id"] not in models
            or descriptor["variant"] not in variants
            or descriptor["condition_id"] not in conditions
        ):
            continue
        base = json.loads(Path(descriptor["output_path"]).read_text(encoding="utf-8"))
        derived = copy.deepcopy(base)
        base_key = base["output_key"]
        derived["control"] = {
            "version": CONTROL_VERSION,
            "base_router_output_key": base_key,
            "intervention": "replace pivotal_proposition with generic end-claim check",
        }
        derived["router"]["judgment"]["pivotal_proposition"] = GENERIC_PROPOSITION
        output_key = hashlib.sha256(
            canonical_json(
                {
                    "control_version": CONTROL_VERSION,
                    "base_router_output_key": base_key,
                    "aligned_packet_key": base["aligned_packet_key"],
                    "derived_router_judgment": derived["router"]["judgment"],
                }
            ).encode()
        ).hexdigest()
        derived["output_key"] = output_key
        path, cached = store_immutable_output(output_root, output_key, derived)
        outputs.append(
            {
                **{
                    key: value
                    for key, value in descriptor.items()
                    if key not in ("output_key", "output_path", "cached_output")
                },
                "base_router_output_key": base_key,
                "output_key": output_key,
                "output_path": str(path),
                "cached_output": cached,
            }
        )
    outputs.sort(
        key=lambda row: (
            row["claim_id"], row["victim_model_id"], row["condition_id"], row["variant"]
        )
    )
    if not outputs:
        raise ValueError("No source rows matched the requested generic-control scope")
    manifest: dict[str, Any] = {
        "warning": "PRIVATE METADATA: never serialize condition/model fields into prompts",
        "experiment_id": args.experiment_id,
        "control_version": CONTROL_VERSION,
        "base_router_experiment_id": source["experiment_id"],
        "generic_proposition": GENERIC_PROPOSITION,
        "dry_run": False,
        "conditions": sorted(conditions),
        "variants": sorted(variants),
        "models": sorted(models),
        "source_rows": len(outputs),
        "expected_outputs": len(outputs),
        "outputs": outputs,
        "failures": [],
    }
    atomic_json(run_root / "private_manifest.json", manifest)
    print(
        json.dumps(
            {
                "status": "complete",
                "experiment_id": args.experiment_id,
                "outputs": len(outputs),
                "cached_outputs": sum(row["cached_output"] for row in outputs),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
