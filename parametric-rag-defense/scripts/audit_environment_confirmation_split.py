#!/usr/bin/env python3
"""Audit the frozen fresh-confirmation split without emitting claim text or labels."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prompt_key(record: dict[str, Any]) -> tuple[str, str]:
    claim = re.sub(r"\s+", " ", str(record["claim"]).strip()).casefold()
    claim_date = re.sub(
        r"\s+", " ", str(record.get("claim_date") or "").strip()
    ).casefold()
    return claim, claim_date


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("configs/splits/environment_confirmation_train_v1.json"),
    )
    parser.add_argument(
        "--train",
        type=Path,
        default=Path("../fighting-fact2fiction-main/DEFAME/data/AVeriTeC/train.json"),
    )
    parser.add_argument(
        "--dev",
        type=Path,
        default=Path("../fighting-fact2fiction-main/DEFAME/data/AVeriTeC/dev.json"),
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    train = json.loads(args.train.read_text(encoding="utf-8"))
    dev = json.loads(args.dev.read_text(encoding="utf-8"))
    claim_ids = [int(value) for value in manifest["confirmation"]["claim_ids"]]
    failures: list[str] = []
    if len(claim_ids) != len(set(claim_ids)):
        failures.append("claim IDs are not unique")
    if len(claim_ids) != int(manifest["confirmation"]["count"]):
        failures.append("manifest count does not match claim IDs")
    if any(value < 0 or value >= min(1000, len(train)) for value in claim_ids):
        failures.append("a claim ID lies outside train shard 0-999")

    selected = [train[value] for value in claim_ids]
    counts = Counter(str(record["label"]) for record in selected)
    if dict(sorted(counts.items())) != dict(
        sorted(manifest["confirmation"]["label_counts"].items())
    ):
        failures.append("selected label counts do not match the manifest")
    if set(counts) - {"Supported", "Refuted"}:
        failures.append("selection contains a non-binary Fact2Fiction label")

    selected_keys = [prompt_key(record) for record in selected]
    dev_keys = {prompt_key(record) for record in dev}
    duplicate_count = len(selected_keys) - len(set(selected_keys))
    dev_overlap = len(set(selected_keys) & dev_keys)
    if duplicate_count:
        failures.append(f"selection contains {duplicate_count} duplicate prompts")
    if dev_overlap:
        failures.append(f"selection overlaps full AVeriTeC dev by {dev_overlap} prompts")

    expected_hashes = manifest["source_sha256"]
    actual_hashes = {
        "AVeriTeC/train.json": sha256_file(args.train),
        "AVeriTeC/dev.json": sha256_file(args.dev),
    }
    if actual_hashes != expected_hashes:
        failures.append("dataset SHA-256 does not match the frozen manifest")

    report = {
        "status": "failed" if failures else "passed",
        "manifest": str(args.manifest),
        "claim_count": len(claim_ids),
        "label_counts": dict(sorted(counts.items())),
        "unique_prompt_count": len(set(selected_keys)),
        "full_dev_prompt_overlap": dev_overlap,
        "source_sha256": actual_hashes,
        "failures": failures,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
