#!/usr/bin/env python3
"""Audit Stage 3 completeness, immutable identity, contracts, and prompt isolation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from parametric_rag_defense.cache import canonical_json
from parametric_rag_defense.stage3_contracts import (
    STAGE3_CONTRACT_VERSION,
    parse_claim_arbiter,
    parse_evidence_critic,
)

_URL = re.compile(r"https?://", re.IGNORECASE)
_ORIGIN = re.compile(r"\b(?:clean|poison):\d+\b", re.IGNORECASE)


def cache_entry(cache_root: Path, key: str) -> dict[str, Any]:
    path = cache_root / "entries" / key[:2] / f"{key}.json"
    entry = json.loads(path.read_text(encoding="utf-8"))
    if entry.get("key") != key:
        raise ValueError(f"cache key mismatch: {path}")
    return entry


def prompt_failure(entry: dict[str, Any]) -> str | None:
    messages = canonical_json(entry["request"]["messages"])
    if _URL.search(messages):
        return "raw URL"
    if _ORIGIN.search(messages):
        return "source-origin identifier"
    lowered = messages.lower()
    for marker in ("fact2fiction_p", "condition_id", "gold_label", "target_label"):
        if marker in lowered:
            return f"forbidden marker {marker}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("artifacts/runs/stage3/stage3_claim_arbiter_v1"),
    )
    parser.add_argument("--cache-root", type=Path, default=Path("artifacts/cache/llm"))
    args = parser.parse_args()

    manifest = json.loads((args.run_root / "private_manifest.json").read_text(encoding="utf-8"))
    failures: list[str] = []
    rows = manifest["outputs"]
    if manifest["failures"]:
        failures.append(f"manifest retains {len(manifest['failures'])} failures")
    if len(rows) != manifest["arbiter_expected"]:
        failures.append("output count does not equal arbiter_expected")
    if manifest["critic_completed"] != manifest["requested_packets"]:
        failures.append("critic count does not equal requested packets")

    output_keys: set[str] = set()
    pair_keys: set[tuple[str, str]] = set()
    critic_keys: set[str] = set()
    arbiter_keys: set[str] = set()
    prompt_failures: list[str] = []
    route_counts: Counter[str] = Counter()
    arbiter_counts: Counter[str] = Counter()
    for row in rows:
        path = Path(row["output_path"])
        try:
            output = json.loads(path.read_text(encoding="utf-8"))
            if output.get("structured_contract_version") != STAGE3_CONTRACT_VERSION:
                raise ValueError("structured contract version mismatch")
            critic_key = output["critic"]["cache_key"]
            arbiter_key = output["arbiter"]["cache_key"]
            identity = {
                "packet_key": output["packet_key"],
                "critic_cache_key": critic_key,
                "arbiter_cache_key": arbiter_key,
                "structured_contract_version": STAGE3_CONTRACT_VERSION,
            }
            expected_key = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
            if output["output_key"] != expected_key or row["output_key"] != expected_key:
                raise ValueError("output identity mismatch")
            critic_judgment = parse_evidence_critic(canonical_json(output["critic"]["judgment"]))
            arbiter_judgment = parse_claim_arbiter(canonical_json(output["arbiter"]["judgment"]))
            if critic_judgment != output["critic"]["judgment"]:
                raise ValueError("critic normalized judgment mismatch")
            if arbiter_judgment != output["arbiter"]["judgment"]:
                raise ValueError("arbiter normalized judgment mismatch")
            critic_entry = cache_entry(args.cache_root, critic_key)
            arbiter_entry = cache_entry(args.cache_root, arbiter_key)
            for role, entry in (("critic", critic_entry), ("arbiter", arbiter_entry)):
                problem = prompt_failure(entry)
                if problem:
                    prompt_failures.append(f"{role}:{entry['key']}: {problem}")
            if critic_entry["metadata"].get("packet_key") != output["packet_key"]:
                raise ValueError("critic cache packet metadata mismatch")
            if arbiter_entry["metadata"].get("packet_key") != output["packet_key"]:
                raise ValueError("arbiter cache packet metadata mismatch")
            if arbiter_entry["metadata"].get("model_id") != output["arbiter"]["model_id"]:
                raise ValueError("arbiter cache model metadata mismatch")
        except Exception as exc:
            failures.append(f"{path}: {exc}")
            continue
        output_keys.add(row["output_key"])
        pair_keys.add((row["packet_key"], row["arbiter_model_id"]))
        critic_keys.add(critic_key)
        arbiter_keys.add(arbiter_key)
        route_counts[row["route"]] += 1
        arbiter_counts[row["arbiter_model_id"]] += 1

    if len(output_keys) != len(rows):
        failures.append("output keys are not unique")
    if len(pair_keys) != len(rows):
        failures.append("packet/arbiter pairs are not unique")
    if len(critic_keys) != manifest["requested_packets"]:
        failures.append("unique critic cache-key count mismatch")
    if len(arbiter_keys) != len(rows):
        failures.append("unique arbiter cache-key count mismatch")
    failures.extend(prompt_failures)
    result = {
        "requested_packets": manifest["requested_packets"],
        "critic_outputs": len(critic_keys),
        "arbiter_outputs": len(rows),
        "unique_output_keys": len(output_keys),
        "arbiter_counts": dict(sorted(arbiter_counts.items())),
        "route_counts": dict(sorted(route_counts.items())),
        "prompt_failures": prompt_failures,
        "validation_failures": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
