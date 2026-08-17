#!/usr/bin/env python3
"""Audit targeted same-model proposition checks and final selectors."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from parametric_rag_defense.aligned_workflow import (
    ALIGNED_FINAL_CONTRACT_VERSION,
    parse_aligned_final,
    selected_prediction,
)
from parametric_rag_defense.cache import canonical_json
from parametric_rag_defense.contracts import parse_internal_judgment

_URL = re.compile(r"https?://", re.IGNORECASE)
_ORIGIN = re.compile(r"\b(?:clean|poison):\d+\b", re.IGNORECASE)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root", type=Path, default=Path("artifacts/runs/stage4/stage4_same_model_c_v1")
    )
    parser.add_argument("--stage1-config", type=Path, default=Path("configs/stage1_matrix.json"))
    args = parser.parse_args()
    config = json.loads(args.stage1_config.read_text(encoding="utf-8"))
    model_names = {model["id"]: model["model"] for model in config["models"]}
    cache_root = Path(config["cache_root"])
    manifest = json.loads((args.run_root / "private_manifest.json").read_text(encoding="utf-8"))
    failures: list[str] = []
    if manifest["failures"]:
        failures.append(f"manifest retains {len(manifest['failures'])} failures")
    if len(manifest["outputs"]) != manifest["target_disagreements"]:
        failures.append("output count differs from target disagreements")
    identities = set()
    output_keys = set()
    check_keys = set()
    final_keys = set()
    endpoint_counts = Counter()
    basis_counts = Counter()
    for row in manifest["outputs"]:
        identity = (row["claim_id"], row["victim_model_id"], row["condition_id"])
        if identity in identities:
            failures.append(f"duplicate row identity: {identity}")
        identities.add(identity)
        try:
            packet = json.loads(Path(row["aligned_packet_path"]).read_text(encoding="utf-8"))
            router = json.loads(Path(row["router_output_path"]).read_text(encoding="utf-8"))
            output = json.loads(Path(row["output_path"]).read_text(encoding="utf-8"))
            if packet["provenance"]["same_model_id"] != row["victim_model_id"]:
                raise ValueError("packet/model mismatch")
            if router["output_key"] != row["router_output_key"] or output["router_output_key"] != row["router_output_key"]:
                raise ValueError("router output identity mismatch")
            check = parse_internal_judgment(canonical_json(output["proposition_check"]["judgment"]))
            final = parse_aligned_final(output["final_selector"]["judgment"])
            if output["derived_prediction"] != selected_prediction(packet, final["selected_endpoint"]):
                raise ValueError("derived Stage C prediction mismatch")
            check_key = output["proposition_check"]["cache_key"]
            final_key = output["final_selector"]["cache_key"]
            for role, key in (("check", check_key), ("final", final_key)):
                entry_path = cache_root / "entries" / key[:2] / f"{key}.json"
                entry = json.loads(entry_path.read_text(encoding="utf-8"))
                if entry["key"] != key:
                    raise ValueError(f"{role} cache-key mismatch")
                if entry["request"]["model"] != model_names[row["victim_model_id"]]:
                    raise ValueError(f"{role} request model differs from victim model")
                if entry["metadata"].get("model_id") != row["victim_model_id"]:
                    raise ValueError(f"{role} metadata model mismatch")
                messages = canonical_json(entry["request"]["messages"])
                if _URL.search(messages) or _ORIGIN.search(messages):
                    raise ValueError(f"{role} prompt exposes source metadata")
                lowered = messages.lower()
                for marker in ("fact2fiction_p", "condition_id", "gold_label", "target_label"):
                    if marker in lowered:
                        raise ValueError(f"{role} prompt contains forbidden marker {marker}")
            expected = hashlib.sha256(
                canonical_json(
                    {
                        "aligned_packet_key": packet["packet_key"],
                        "router_output_key": router["output_key"],
                        "proposition_cache_key": check_key,
                        "final_cache_key": final_key,
                        "contract_version": ALIGNED_FINAL_CONTRACT_VERSION,
                    }
                ).encode()
            ).hexdigest()
            if output["output_key"] != expected or row["output_key"] != expected:
                raise ValueError("Stage C output identity mismatch")
            output_keys.add(expected)
            check_keys.add(check_key)
            final_keys.add(final_key)
            endpoint_counts[final["selected_endpoint"]] += 1
            basis_counts[check["knowledge_basis"]] += 1
        except Exception as exc:
            failures.append(f"{identity}: {exc}")
    # Proposition checks and final selectors are content addressed and may be shared when a
    # low-rate attacked row has the exact same prompt-visible endpoint packet as its clean row.
    # The experimental row identities and immutable output identities must remain unique.
    if len(output_keys) != len(manifest["outputs"]):
        failures.append("output keys are not unique")
    result = {
        "outputs": len(manifest["outputs"]),
        "unique_proposition_checks": len(check_keys),
        "unique_final_selectors": len(final_keys),
        "selected_endpoints": dict(sorted(endpoint_counts.items())),
        "proposition_knowledge_basis": dict(sorted(basis_counts.items())),
        "validation_failures": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
