#!/usr/bin/env python3
"""Create deterministic Fact2Fiction-compatible development and locked-test splits.

Split manifests contain IDs and aggregate counts but no per-claim gold labels. Evaluation labels are
written under ignored artifacts so inference code does not need to load them.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

FIXED_DEVELOPMENT_IDS = [0, 3, 4, 5, 6, 8, 12, 14, 17, 19, 20, 22, 23, 25, 27, 28, 31, 37, 42, 54]
DEVELOPMENT_TARGETS = {
    "Refuted": 50,
    "Supported": 50,
}
TEST_TARGETS = {
    "Refuted": 50,
    "Supported": 50,
}


def canonical_label(label: str) -> str:
    if label == "Conflicting Evidence/Cherrypicking":
        return "Conflicting Evidence"
    return label


def prompt_key(claim: dict[str, Any]) -> tuple[str, str]:
    """Identity visible to the endpoint; duplicates cannot be independent examples."""

    return (claim["claim"].strip(), claim.get("claim_date") or "unknown")


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
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("../fighting-fact2fiction-main/DEFAME/data/AVeriTeC/dev.json"),
    )
    parser.add_argument("--seed", type=int, default=20260808)
    parser.add_argument("--split-output", type=Path, default=Path("configs/splits/stage1.json"))
    parser.add_argument(
        "--base-split",
        type=Path,
        default=Path("configs/splits/stage1_v2_100dev_100locked_with_duplicates.json"),
        help="Archived prior split whose unique completed IDs remain assigned consistently",
    )
    parser.add_argument(
        "--labels-output",
        type=Path,
        default=Path("artifacts/evaluation/stage1_labels.json"),
    )
    args = parser.parse_args()

    claims = json.loads(args.dataset.resolve().read_text(encoding="utf-8"))
    labels = {index: canonical_label(item["label"]) for index, item in enumerate(claims)}
    rng = random.Random(args.seed)

    split_output = args.split_output.resolve()
    base_split_path = args.base_split.resolve()
    if not base_split_path.exists():
        if not split_output.exists():
            raise FileNotFoundError(
                f"Neither base split nor existing split exists: {base_split_path}, {split_output}"
            )
        base_split = json.loads(split_output.read_text(encoding="utf-8"))
        atomic_json(base_split_path, base_split)
    else:
        base_split = json.loads(base_split_path.read_text(encoding="utf-8"))

    base_development = list(base_split["development"]["claim_ids"])
    base_locked = list(base_split["locked_test"]["claim_ids"])
    base_diagnostic = list(
        base_split.get("four_label_diagnostic", {}).get("claim_ids", [])
    ) or [
        claim_id
        for claim_id in base_development
        if labels[claim_id] not in DEVELOPMENT_TARGETS
    ]

    used_prompt_keys: set[tuple[str, str]] = set()

    def preserve_unique(ids: list[int], allowed_labels: dict[str, int] | None) -> list[int]:
        retained: list[int] = []
        for claim_id in ids:
            if allowed_labels is not None and labels[claim_id] not in allowed_labels:
                continue
            key = prompt_key(claims[claim_id])
            if key in used_prompt_keys:
                continue
            used_prompt_keys.add(key)
            retained.append(claim_id)
        return retained

    # Priority is deterministic: retain collected development prompts, the historical diagnostic,
    # then locked assignments. Endpoint outcomes never influence duplicate removal.
    development = preserve_unique(base_development, DEVELOPMENT_TARGETS)
    diagnostic_ids = preserve_unique(base_diagnostic, None)
    test = preserve_unique(base_locked, TEST_TARGETS)
    excluded = set(base_development) | set(base_locked) | set(base_diagnostic)
    current_development = Counter(labels[claim_id] for claim_id in development)
    current_test = Counter(labels[claim_id] for claim_id in test)
    by_label: dict[str, list[int]] = defaultdict(list)
    for claim_id, label in labels.items():
        if claim_id not in excluded:
            by_label[label].append(claim_id)
    for values in by_label.values():
        rng.shuffle(values)

    for label, target in DEVELOPMENT_TARGETS.items():
        needed = target - current_development[label]
        if needed < 0:
            raise ValueError(
                f"Preserved development IDs exceed target for {label}: "
                f"{current_development[label]} > {target}"
            )
        selected: list[int] = []
        while by_label[label] and len(selected) < needed:
            candidate = by_label[label].pop(0)
            key = prompt_key(claims[candidate])
            if key in used_prompt_keys:
                continue
            used_prompt_keys.add(key)
            selected.append(candidate)
        if len(selected) < needed:
            raise ValueError(f"Not enough unique {label} claims for development")
        development.extend(selected)

    for label, target in TEST_TARGETS.items():
        needed = target - current_test[label]
        if needed < 0:
            raise ValueError(
                f"Preserved locked IDs exceed target for {label}: {current_test[label]} > {target}"
            )
        selected = []
        while by_label[label] and len(selected) < needed:
            candidate = by_label[label].pop(0)
            key = prompt_key(claims[candidate])
            if key in used_prompt_keys:
                continue
            used_prompt_keys.add(key)
            selected.append(candidate)
        if len(selected) < needed:
            raise ValueError(f"Not enough unique {label} claims for test")
        test.extend(selected)

    development.sort()
    test.sort()
    if set(development) & set(test):
        raise AssertionError("Development and test overlap")
    combined_ids = development + test + diagnostic_ids
    if len({prompt_key(claims[claim_id]) for claim_id in combined_ids}) != len(combined_ids):
        raise AssertionError("Exact claim/date prompt overlap remains across splits")

    development_counts = Counter(labels[claim_id] for claim_id in development)
    test_counts = Counter(labels[claim_id] for claim_id in test)
    split = {
        "split_schema_version": 3,
        "dataset": "AVeriTeC dev",
        "dataset_records": len(claims),
        "seed": args.seed,
        "development": {
            "claim_ids": development,
            "count": len(development),
            "label_counts": dict(sorted(development_counts.items())),
            "contains_legacy_conflict_probe": True,
            "fact2fiction_binary_candidates": True,
            "unique_internal_prompts": True,
        },
        "locked_test": {
            "claim_ids": test,
            "count": len(test),
            "label_counts": dict(sorted(test_counts.items())),
            "fact2fiction_binary_candidates": True,
            "unique_internal_prompts": True,
        },
        "four_label_diagnostic": {
            "claim_ids": sorted(diagnostic_ids),
            "count": len(diagnostic_ids),
            "label_counts": dict(
                sorted(Counter(labels[claim_id] for claim_id in diagnostic_ids).items())
            ),
            "note": "Completed v1 non-binary outputs retained as exploratory cached artifacts.",
            "unique_internal_prompts": True,
        },
        "policy": {
            "development_only_ids": FIXED_DEVELOPMENT_IDS,
            "base_split_manifest": str(args.base_split),
            "fact2fiction_filter_1": "gold label is Supported or Refuted",
            "fact2fiction_filter_2": "clean victim prediction equals gold; applied per victim later",
            "duplicate_policy": "exact normalized claim text and claim date are unique across all splits",
            "open_test_only_after_prompts_frozen": True,
            "gold_labels_allowed_in_inference": False,
        },
    }
    evaluation = {
        "warning": "EVALUATION ONLY: never join labels into inference prompts",
        "development": {str(i): labels[i] for i in development},
        "locked_test": {str(i): labels[i] for i in test},
        "four_label_diagnostic": {str(i): labels[i] for i in diagnostic_ids},
    }
    atomic_json(split_output, split)
    atomic_json(args.labels_output.resolve(), evaluation)
    print(f"development={len(development)} {dict(sorted(development_counts.items()))}")
    print(f"locked_test={len(test)} {dict(sorted(test_counts.items()))}")
    print(f"unique_prompt_keys={len(used_prompt_keys)}")
    print(f"wrote {args.split_output.resolve()}")


if __name__ == "__main__":
    main()
