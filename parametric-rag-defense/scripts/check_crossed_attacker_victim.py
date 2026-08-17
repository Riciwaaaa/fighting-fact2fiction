#!/usr/bin/env python3
"""Audit coverage, identities, poison reuse, and victim-model calls in the crossed matrix."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from parametric_rag_defense.cache import canonical_json

MODELS = ("glm52", "llama31_70b", "qwen35_35b_a3b")
_URL = re.compile(r"https?://", re.IGNORECASE)
_ORIGIN = re.compile(r"\b(?:clean|poison):\d+\b", re.IGNORECASE)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(
            "artifacts/runs/stage1/development/rag/stage1_crossed_av_1pct_v1/"
            "manifests/crossed_manifest.json"
        ),
    )
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    model_names = {model["id"]: model["model"] for model in config["models"]}
    cache_root = Path(config["cache_root"])
    failures: list[str] = []
    if manifest["failures"]:
        failures.append(f"manifest retains {len(manifest['failures'])} failures")
    if len(manifest["common_claim_ids"]) != 61:
        failures.append("common claim scope is not 61")
    if manifest["requested"] != 61 * 9 or len(manifest["successes"]) != 61 * 9:
        failures.append("matrix output count is incomplete")
    identities = set()
    cells = Counter()
    off_diagonal = 0
    for row in manifest["successes"]:
        identity = (row["attacker_model_id"], row["victim_model_id"], row["claim_id"])
        if identity in identities:
            failures.append(f"duplicate identity: {identity}")
        identities.add(identity)
        cells[identity[:2]] += 1
        try:
            artifact = json.loads(Path(row["artifact_path"]).read_text(encoding="utf-8"))
            if artifact["task"]["claim_id"] != row["claim_id"]:
                raise ValueError("claim mismatch")
            if artifact["task"].get("model_id", artifact["task"].get("victim_model_id")) != row["victim_model_id"]:
                raise ValueError("victim mismatch")
            if artifact["task"]["condition"]["id"] != "fact2fiction_p0.01":
                raise ValueError("condition mismatch")
            if row["attacker_model_id"] == row["victim_model_id"]:
                if not row["reused_diagonal"]:
                    raise ValueError("diagonal was not marked reused")
                continue
            off_diagonal += 1
            if row["reused_diagonal"]:
                raise ValueError("off-diagonal marked as diagonal")
            if artifact["task"]["attacker_model_id"] != row["attacker_model_id"]:
                raise ValueError("attacker mismatch")
            provenance = artifact["provenance"]
            if provenance["attack_generator_model_id"] != row["attacker_model_id"]:
                raise ValueError("attacker provenance mismatch")
            trace = json.loads(Path(row["trace_path"]).read_text(encoding="utf-8"))
            material = json.loads(Path(trace["source_poison_material"]).read_text(encoding="utf-8"))
            if material["model_id"] != row["attacker_model_id"]:
                raise ValueError("source poison generator mismatch")
            if material["documents_sha256"] != provenance["source_poison_documents_sha256"]:
                raise ValueError("source poison hash mismatch")
            for role in ("plan", "answers", "verdict"):
                for receipt in trace["llm_receipts"][role]:
                    key = receipt["cache_key"]
                    entry = json.loads(
                        (cache_root / "entries" / key[:2] / f"{key}.json").read_text(encoding="utf-8")
                    )
                    if entry["request"]["model"] != model_names[row["victim_model_id"]]:
                        raise ValueError(f"{role} call does not use victim model")
                    messages = canonical_json(entry["request"]["messages"])
                    if _URL.search(messages) or _ORIGIN.search(messages):
                        raise ValueError(f"{role} prompt leaks source metadata")
                    lowered = messages.lower()
                    for marker in ("attacker_model_id", "victim_model_id", "fact2fiction_p"):
                        if marker in lowered:
                            raise ValueError(f"{role} prompt leaks experimental marker {marker}")
        except Exception as exc:
            failures.append(f"{identity}: {exc}")
    for attacker in MODELS:
        for victim in MODELS:
            if cells[(attacker, victim)] != 61:
                failures.append(f"cell {attacker}/{victim} has {cells[(attacker, victim)]} rows")
    result = {
        "outputs": len(manifest["successes"]),
        "off_diagonal_outputs": off_diagonal,
        "cell_counts": {f"{a}->{v}": cells[(a, v)] for a in MODELS for v in MODELS},
        "validation_failures": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
