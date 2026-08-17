#!/usr/bin/env python3
"""Audit completeness and attacker isolation of crossed-defense Stage 2 packets."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from parametric_rag_defense.cache import canonical_json
from parametric_rag_defense.stage2_packets import validate_visible_packet

MODELS = ("glm52", "llama31_70b", "qwen35_35b_a3b")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root", type=Path, default=Path("artifacts/runs/stage2/stage2_crossed_defense_v2")
    )
    args = parser.parse_args()
    manifest = json.loads((args.run_root / "manifest.json").read_text(encoding="utf-8"))
    index = json.loads((args.run_root / "private_index.json").read_text(encoding="utf-8"))
    failures: list[str] = []
    digest = hashlib.sha256(canonical_json(index).encode()).hexdigest()
    if digest != manifest["private_index_sha256"]:
        failures.append("private index digest mismatch")
    rows = index["rows"]
    if len(rows) != 849 or manifest["packet_count"] != 849:
        failures.append("expected 849 combined rows")
    identities = set()
    packets = set()
    tasks = set()
    clean = Counter()
    cells = Counter()
    condition_map = index["attack_condition_map"]
    reverse_conditions = {condition: attacker for attacker, condition in condition_map.items()}
    for row in rows:
        identity = (row["claim_id"], row["victim_model_id"], row["condition_id"])
        if identity in identities:
            failures.append(f"duplicate identity: {identity}")
        identities.add(identity)
        try:
            packet = json.loads(Path(row["packet_path"]).read_text(encoding="utf-8"))
            endpoint = json.loads(Path(row["rag_artifact_path"]).read_text(encoding="utf-8"))
            validate_visible_packet(packet["visible"])
            visible = canonical_json(packet["visible"]).lower()
            for marker in (*MODELS, "attacker_model_id", "cross_glm52", "cross_llama", "cross_qwen"):
                if marker.lower() in visible:
                    raise ValueError(f"attacker/model marker visible: {marker}")
            expected_packet = hashlib.sha256(
                canonical_json(
                    {
                        "packet_schema_version": packet["packet_schema_version"],
                        "rag_task_key": packet["provenance"]["rag_task_key"],
                        "internal_cache_keys": packet["provenance"]["internal_cache_keys"],
                    }
                ).encode()
            ).hexdigest()
            if packet["packet_key"] != expected_packet or row["packet_key"] != expected_packet:
                raise ValueError("packet identity mismatch")
            if endpoint["task_key"] != row["rag_task_key"]:
                raise ValueError("endpoint task mismatch")
            victim = endpoint["task"].get("model_id", endpoint["task"].get("victim_model_id"))
            if victim != row["victim_model_id"]:
                raise ValueError("endpoint victim mismatch")
            if row["condition_id"] == "clean":
                if row["attacker_model_id"] is not None:
                    raise ValueError("clean row has attacker metadata")
                clean[row["victim_model_id"]] += 1
            else:
                attacker = reverse_conditions.get(row["condition_id"])
                if attacker is None or attacker != row["attacker_model_id"]:
                    raise ValueError("private attacker/condition mismatch")
                cells[(attacker, row["victim_model_id"])] += 1
        except Exception as exc:
            failures.append(f"{identity}: {exc}")
        packets.add(row["packet_key"])
        tasks.add(row["rag_task_key"])
    if len(packets) != 849 or len(tasks) != 849:
        failures.append("packet or endpoint task keys are not unique")
    for model in MODELS:
        if clean[model] != 100:
            failures.append(f"clean/{model} has {clean[model]} rows")
        for attacker in MODELS:
            if cells[(attacker, model)] != 61:
                failures.append(f"{attacker}->{model} has {cells[(attacker, model)]} rows")
    result = {
        "packets": len(rows),
        "clean_counts": dict(sorted(clean.items())),
        "crossed_cell_counts": {
            f"{attacker}->{victim}": cells[(attacker, victim)]
            for attacker in MODELS
            for victim in MODELS
        },
        "failures": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
