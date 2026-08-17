#!/usr/bin/env python3
"""Audit exact same-model router outputs, identities, contracts, and prompt isolation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from parametric_rag_defense.aligned_workflow import (
    ALIGNED_ROUTER_CONTRACT_VERSION,
    parse_aligned_router,
    selected_prediction,
)
from parametric_rag_defense.cache import canonical_json
from parametric_rag_defense.stage2_packets import validate_visible_packet

_URL = re.compile(r"https?://", re.IGNORECASE)
_ORIGIN = re.compile(r"\b(?:clean|poison):\d+\b", re.IGNORECASE)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root", type=Path, default=Path("artifacts/runs/stage3/stage3_same_model_ab_v1")
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
    if manifest["dry_run"]:
        failures.append("manifest is a dry run")
    if len(manifest["outputs"]) != manifest["expected_outputs"]:
        failures.append("output count differs from expectation")
    identities = set()
    output_keys = set()
    cache_keys = set()
    variants = Counter()
    models = Counter()
    routes = Counter()
    for row in manifest["outputs"]:
        identity = (
            row["claim_id"], row["victim_model_id"], row["condition_id"], row["variant"]
        )
        if identity in identities:
            failures.append(f"duplicate row identity: {identity}")
        identities.add(identity)
        try:
            packet = json.loads(Path(row["aligned_packet_path"]).read_text(encoding="utf-8"))
            output = json.loads(Path(row["output_path"]).read_text(encoding="utf-8"))
            validate_visible_packet(packet["visible"])
            if packet["provenance"]["same_model_id"] != row["victim_model_id"]:
                raise ValueError("same-model provenance mismatch")
            if "memory_only_assessments" in packet["visible"]:
                raise ValueError("plural memory candidate collection leaked into aligned packet")
            if row["variant"] == "endpoint_only" and "questions" in packet["visible"]["retrieval_assessment"]:
                raise ValueError("endpoint-only packet contains retrieval questions")
            if row["variant"] == "evidence_aware" and "questions" not in packet["visible"]["retrieval_assessment"]:
                raise ValueError("evidence-aware packet lacks retrieval questions")
            judgment = parse_aligned_router(output["router"]["judgment"])
            if output["derived_prediction"] != selected_prediction(
                packet, judgment["provisional_endpoint"]
            ):
                raise ValueError("derived endpoint prediction mismatch")
            cache_key = output["router"]["cache_key"]
            entry_path = cache_root / "entries" / cache_key[:2] / f"{cache_key}.json"
            entry = json.loads(entry_path.read_text(encoding="utf-8"))
            if entry["key"] != cache_key:
                raise ValueError("cache key mismatch")
            if entry["request"]["model"] != model_names[row["victim_model_id"]]:
                raise ValueError("router request model differs from victim model")
            if entry["metadata"].get("model_id") != row["victim_model_id"]:
                raise ValueError("router cache metadata model mismatch")
            messages = canonical_json(entry["request"]["messages"])
            if _URL.search(messages) or _ORIGIN.search(messages):
                raise ValueError("source metadata leaked into router prompt")
            lowered = messages.lower()
            for marker in ("fact2fiction_p", "condition_id", "gold_label", "target_label"):
                if marker in lowered:
                    raise ValueError(f"forbidden prompt marker: {marker}")
            expected_output_key = hashlib.sha256(
                canonical_json(
                    {
                        "aligned_packet_key": packet["packet_key"],
                        "router_cache_key": cache_key,
                        "contract_version": ALIGNED_ROUTER_CONTRACT_VERSION,
                    }
                ).encode()
            ).hexdigest()
            if output["output_key"] != expected_output_key or row["output_key"] != expected_output_key:
                raise ValueError("output identity mismatch")
            output_keys.add(expected_output_key)
            cache_keys.add(cache_key)
            variants[row["variant"]] += 1
            models[row["victim_model_id"]] += 1
            routes[judgment["route"]] += 1
        except Exception as exc:
            failures.append(f"{identity}: {exc}")
    if len(output_keys) != len(manifest["outputs"]):
        failures.append("output keys are not unique")
    # Cache keys identify prompt/model/decoding requests, not experimental rows. A low-rate
    # attacked row can legitimately have the same visible endpoint packet as its clean row when
    # no injected document changes the normalized RAG assessment. Row and immutable output
    # identities must remain unique; sharing an exact request is the intended cache behavior.
    result = {
        "outputs": len(manifest["outputs"]),
        "unique_router_calls": len(cache_keys),
        "variants": dict(sorted(variants.items())),
        "models": dict(sorted(models.items())),
        "routes": dict(sorted(routes.items())),
        "validation_failures": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
