#!/usr/bin/env python3
"""Independently audit Stage 2 packet completeness, identity, and inference isolation."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from parametric_rag_defense.cache import canonical_json
from parametric_rag_defense.stage2_packets import validate_visible_packet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root", type=Path, default=Path("artifacts/runs/stage2/stage2_signal_v1")
    )
    args = parser.parse_args()
    manifest = json.loads((args.run_root / "manifest.json").read_text(encoding="utf-8"))
    private_index = json.loads((args.run_root / "private_index.json").read_text(encoding="utf-8"))
    observed_index_digest = hashlib.sha256(canonical_json(private_index).encode()).hexdigest()
    failures: list[str] = []
    if observed_index_digest != manifest["private_index_sha256"]:
        failures.append("private index digest mismatch")
    rows = private_index["rows"]
    if len(rows) != manifest["packet_count"] or len(rows) != manifest["expected_packet_count"]:
        failures.append("packet count does not equal manifest/expected count")
    condition_counts: Counter[str] = Counter()
    victim_counts: Counter[str] = Counter()
    packet_keys: set[str] = set()
    task_keys: set[str] = set()
    for row in rows:
        path = Path(row["packet_path"])
        try:
            packet = json.loads(path.read_text(encoding="utf-8"))
            validate_visible_packet(packet["visible"])
            identity = {
                "packet_schema_version": packet["packet_schema_version"],
                "rag_task_key": packet["provenance"]["rag_task_key"],
                "internal_cache_keys": packet["provenance"]["internal_cache_keys"],
            }
            expected_key = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
            if packet["packet_key"] != expected_key or row["packet_key"] != expected_key:
                failures.append(f"packet identity mismatch: {path}")
            if packet["provenance"]["rag_task_key"] != row["rag_task_key"]:
                failures.append(f"RAG task identity mismatch: {path}")
            visible_aliases = {
                candidate["candidate_id"]
                for candidate in packet["visible"]["memory_only_assessments"]
            }
            provenance_aliases = set(packet["provenance"]["internal_candidate_map"])
            if visible_aliases != provenance_aliases:
                failures.append(f"candidate alias mismatch: {path}")
        except Exception as exc:
            failures.append(f"{path}: {exc}")
            continue
        packet_keys.add(row["packet_key"])
        task_keys.add(row["rag_task_key"])
        condition_counts[row["condition_id"]] += 1
        victim_counts[row["victim_model_id"]] += 1
    if len(packet_keys) != len(rows):
        failures.append("packet keys are not unique")
    if len(task_keys) != len(rows):
        failures.append("RAG task keys are not unique")
    if dict(sorted(condition_counts.items())) != manifest["condition_counts"]:
        failures.append("condition counts disagree with manifest")
    if dict(sorted(victim_counts.items())) != manifest["victim_counts"]:
        failures.append("victim counts disagree with manifest")
    result = {
        "packet_count": len(rows),
        "unique_packet_keys": len(packet_keys),
        "unique_rag_task_keys": len(task_keys),
        "condition_counts": dict(sorted(condition_counts.items())),
        "victim_counts": dict(sorted(victim_counts.items())),
        "failures": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
