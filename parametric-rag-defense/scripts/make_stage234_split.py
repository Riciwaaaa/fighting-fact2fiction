#!/usr/bin/env python3
"""Freeze claim-grouped method-development and validation partitions for Stages 2--4.

The script uses gold labels only to balance the two partitions.  The tracked manifest contains
claim IDs and aggregate counts, never per-claim labels.  Every RAG condition, victim model, and
internal-model output for a claim inherits the claim's partition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1-split", type=Path, default=Path("configs/splits/stage1.json"))
    parser.add_argument(
        "--labels", type=Path, default=Path("artifacts/evaluation/stage1_labels.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("configs/splits/stage234_development.json")
    )
    parser.add_argument("--seed", type=int, default=20260809)
    parser.add_argument("--design-per-label", type=int, default=30)
    args = parser.parse_args()

    stage1 = json.loads(args.stage1_split.read_text(encoding="utf-8"))
    labels_artifact = json.loads(args.labels.read_text(encoding="utf-8"))
    development_ids = [int(value) for value in stage1["development"]["claim_ids"]]
    labels = labels_artifact["development"]

    by_label: dict[str, list[int]] = defaultdict(list)
    for claim_id in development_ids:
        label = labels.get(str(claim_id))
        if label not in {"Supported", "Refuted"}:
            raise ValueError(f"Development claim {claim_id} has an unexpected label: {label!r}")
        by_label[label].append(claim_id)

    rng = random.Random(args.seed)
    design: list[int] = []
    validation: list[int] = []
    design_counts: dict[str, int] = {}
    validation_counts: dict[str, int] = {}
    for label in sorted(by_label):
        bucket = sorted(by_label[label])
        rng.shuffle(bucket)
        if len(bucket) <= args.design_per_label:
            raise ValueError(
                f"Need a non-empty validation partition for {label}; "
                f"found {len(bucket)}, design requested {args.design_per_label}"
            )
        selected = bucket[: args.design_per_label]
        held_out = bucket[args.design_per_label :]
        design.extend(selected)
        validation.extend(held_out)
        design_counts[label] = len(selected)
        validation_counts[label] = len(held_out)

    design.sort()
    validation.sort()
    if set(design) & set(validation):
        raise AssertionError("Stage 2--4 design and validation partitions overlap")
    if sorted(design + validation) != sorted(development_ids):
        raise AssertionError("Stage 2--4 partitions do not cover Stage 1 development exactly")

    identity = {
        "seed": args.seed,
        "design_claim_ids": design,
        "validation_claim_ids": validation,
    }
    manifest = {
        "split_schema_version": 1,
        "name": "stage234_development",
        "parent_split": str(args.stage1_split),
        "parent_partition": "development",
        "seed": args.seed,
        "split_digest_sha256": hashlib.sha256(canonical_json(identity).encode()).hexdigest(),
        "method_design": {
            "claim_ids": design,
            "count": len(design),
            "label_counts": dict(sorted(design_counts.items())),
            "allowed_uses": [
                "signal characterization",
                "prompt development",
                "workflow selection",
                "threshold and escalation-budget selection",
            ],
        },
        "development_validation": {
            "claim_ids": validation,
            "count": len(validation),
            "label_counts": dict(sorted(validation_counts.items())),
            "allowed_uses": ["one-shot development validation after workflow freeze"],
        },
        "policy": {
            "grouping_unit": "claim_id",
            "grouping_rule": "all models, seeds, RAG conditions, and attack strengths for one claim remain together",
            "stratification": "30 Supported and 30 Refuted claims for method design; the remainder for validation",
            "endpoint_outcomes_used_for_split": False,
            "per_claim_gold_labels_in_manifest": False,
            "locked_test_membership_changed": False,
            "locked_test_outputs_opened": False,
        },
    }
    atomic_json(args.output, manifest)
    print(f"method_design={len(design)} {dict(sorted(design_counts.items()))}")
    print(f"development_validation={len(validation)} {dict(sorted(validation_counts.items()))}")
    print(f"digest={manifest['split_digest_sha256']}")
    print(f"wrote {args.output.resolve()}")


if __name__ == "__main__":
    main()
