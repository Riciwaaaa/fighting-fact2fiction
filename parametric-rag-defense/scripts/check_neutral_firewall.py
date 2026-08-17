#!/usr/bin/env python3
"""Audit neutral planning, retrieval-isolated checks, and firewalled endpoint selectors."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from parametric_rag_defense.aligned_workflow import (
    candidate_prediction,
    parse_aligned_final,
)
from parametric_rag_defense.cache import canonical_json
from parametric_rag_defense.contracts import parse_internal_judgment
from parametric_rag_defense.neutral_firewall import (
    FIREWALLED_SELECTOR_CONTRACT_VERSION,
    NEUTRAL_PLAN_CONTRACT_VERSION,
    endpoint_prediction,
    parse_neutral_plan,
)

_URL = re.compile(r"https?://", re.IGNORECASE)
_ORIGIN = re.compile(r"\b(?:clean|poison):\d+\b", re.IGNORECASE)
_FORBIDDEN_MARKERS = (
    "condition_id",
    "attacker_model_id",
    "fact2fiction_p",
    "cross_glm52_p",
    "cross_llama31_70b_p",
    "cross_qwen35_35b_a3b_p",
    "gold_label",
    "target_label",
    "retrieval_assessment",
    "memory_only_assessment",
    "retrieved_excerpts",
    '"coverage"',
    '"justification"',
    '"agreement_fraction"',
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("artifacts/runs/stage5/stage5_neutral_firewall_v1"),
    )
    parser.add_argument(
        "--stage1-config", type=Path, default=Path("configs/stage1_crossed_defense.json")
    )
    args = parser.parse_args()
    config = json.loads(args.stage1_config.read_text(encoding="utf-8"))
    model_names = {model["id"]: model["model"] for model in config["models"]}
    cache_root = Path(config["cache_root"])
    manifest = json.loads((args.run_root / "private_manifest.json").read_text(encoding="utf-8"))
    failures: list[str] = []
    if manifest["failures"]:
        failures.append(f"manifest retains {len(manifest['failures'])} failures")
    if len(manifest["outputs"]) != manifest["expected_output_rows"]:
        failures.append("output count differs from expected output rows")
    identities = set()
    output_keys = set()
    selector_keys = set()
    plan_keys = set()
    method_check_keys = set()
    control_check_keys = set()
    variant_counts = Counter()
    selected_endpoints = Counter()
    fail_closed_outputs = 0
    cache_entries: dict[str, dict] = {}

    def cache_entry(key: str, *, victim_model_id: str, role: str) -> dict:
        if key not in cache_entries:
            path = cache_root / "entries" / key[:2] / f"{key}.json"
            cache_entries[key] = json.loads(path.read_text(encoding="utf-8"))
        entry = cache_entries[key]
        if entry["key"] != key:
            raise ValueError(f"{role} cache-key mismatch")
        if entry["request"]["model"] != model_names[victim_model_id]:
            raise ValueError(f"{role} request model differs from victim model")
        if entry["metadata"].get("model_id") != victim_model_id:
            raise ValueError(f"{role} metadata model mismatch")
        messages = canonical_json(entry["request"]["messages"])
        if _URL.search(messages) or _ORIGIN.search(messages):
            raise ValueError(f"{role} prompt exposes source metadata")
        lowered = messages.lower()
        for marker in _FORBIDDEN_MARKERS:
            if marker in lowered:
                raise ValueError(f"{role} prompt contains forbidden marker {marker}")
        return entry

    for row in manifest["outputs"]:
        identity = (
            row["claim_id"],
            row["victim_model_id"],
            row["condition_id"],
            row["variant"],
        )
        if identity in identities:
            failures.append(f"duplicate row identity: {identity}")
        identities.add(identity)
        try:
            packet = json.loads(Path(row["aligned_packet_path"]).read_text(encoding="utf-8"))
            output = json.loads(Path(row["output_path"]).read_text(encoding="utf-8"))
            if packet["packet_key"] != row["aligned_packet_key"]:
                raise ValueError("aligned packet identity mismatch")
            if output["model_id"] != row["victim_model_id"]:
                raise ValueError("workflow output model mismatch")
            endpoint_labels = {
                "retrieval": packet["visible"]["retrieval_assessment"]["verdict"],
                "memory": candidate_prediction(packet["visible"]["memory_only_assessment"]),
            }
            if output["endpoint_labels"] != endpoint_labels:
                raise ValueError("minimal endpoint labels mismatch")
            selector = parse_aligned_final(output["selector"]["judgment"])
            prediction = endpoint_prediction(endpoint_labels, selector["selected_endpoint"])
            if output["derived_prediction"] != prediction or row["prediction"] != prediction:
                raise ValueError("derived prediction does not copy selected endpoint")
            if output.get("resolution") == manifest.get("fail_closed_resolution"):
                if row["case_key"] not in manifest.get("fail_closed_case_keys", []):
                    raise ValueError("undeclared fail-closed case")
                if selector["selected_endpoint"] != "memory":
                    raise ValueError("fail-closed output does not select memory")
                if output["selector"]["cache_key"] is not None:
                    raise ValueError("fail-closed output unexpectedly cites a selector call")
                components = output["analysis_bundle"]
                receipts = components.get("failed_call_receipts")
                if not isinstance(receipts, list) or not receipts:
                    raise ValueError("fail-closed output lacks failed-call receipts")
                if any(receipt.get("contract_ok") for receipt in receipts):
                    raise ValueError("fail-closed output cites a contract-valid attempt")
                for receipt in receipts:
                    entry = cache_entry(
                        receipt["cache_key"],
                        victim_model_id=row["victim_model_id"],
                        role="failed analysis attempt",
                    )
                    if entry["response"].get("contract_ok") is not False:
                        raise ValueError("failed-call receipt points to a valid cache entry")
                expected = hashlib.sha256(
                    canonical_json(
                        {
                            "workflow": "stage5-neutral-firewall-v1",
                            "variant": row["variant"],
                            "selector_identity": (
                                row["case_key"],
                                endpoint_labels["retrieval"],
                                endpoint_labels["memory"],
                            ),
                            "resolution": manifest["fail_closed_resolution"],
                            "failed_call_cache_keys": [
                                receipt["cache_key"] for receipt in receipts
                            ],
                        }
                    ).encode()
                ).hexdigest()
                if output["output_key"] != expected or row["output_key"] != expected:
                    raise ValueError("fail-closed output identity mismatch")
                output_keys.add(expected)
                selected_endpoints[(row["variant"], "memory")] += 1
                variant_counts[row["variant"]] += 1
                fail_closed_outputs += 1
                continue
            selector_key = output["selector"]["cache_key"]
            selector_entry = cache_entry(
                selector_key, victim_model_id=row["victim_model_id"], role="selector"
            )
            if selector_entry["metadata"].get("bundle_variant") != row["variant"]:
                raise ValueError("selector bundle variant mismatch")
            components = output["analysis_bundle"]
            check_keys = components["check_cache_keys"]
            plan_key = components["plan_cache_key"]
            if row["variant"] == "neutral_countercheck":
                if not isinstance(plan_key, str) or len(check_keys) != 2:
                    raise ValueError("neutral variant component count mismatch")
                parse_neutral_plan(components["visible"]["neutral_plan"])
                parse_internal_judgment(
                    canonical_json(components["visible"]["support_check"])
                )
                parse_internal_judgment(
                    canonical_json(components["visible"]["counter_check"])
                )
                cache_entry(plan_key, victim_model_id=row["victim_model_id"], role="plan")
                plan_keys.add(plan_key)
                for key in check_keys:
                    cache_entry(
                        key, victim_model_id=row["victim_model_id"], role="neutral check"
                    )
                    method_check_keys.add(key)
            elif row["variant"] == "direct_deliberation":
                if plan_key is not None or len(check_keys) != 3:
                    raise ValueError("direct-control component count mismatch")
                assessments = components["visible"]["direct_assessments"]
                if len(assessments) != 3:
                    raise ValueError("direct-control visible assessment count mismatch")
                for assessment in assessments:
                    parse_internal_judgment(canonical_json(assessment["judgment"]))
                for key in check_keys:
                    cache_entry(
                        key, victim_model_id=row["victim_model_id"], role="direct control"
                    )
                    control_check_keys.add(key)
            else:
                raise ValueError(f"unexpected variant: {row['variant']}")
            expected = hashlib.sha256(
                canonical_json(
                    {
                        "workflow": "stage5-neutral-firewall-v1",
                        "variant": row["variant"],
                        "selector_identity": (
                            row["case_key"],
                            endpoint_labels["retrieval"],
                            endpoint_labels["memory"],
                        ),
                        "plan_cache_key": plan_key,
                        "check_cache_keys": check_keys,
                        "selector_cache_key": selector_key,
                        "plan_contract": (
                            NEUTRAL_PLAN_CONTRACT_VERSION
                            if row["variant"] == "neutral_countercheck"
                            else None
                        ),
                        "selector_contract": FIREWALLED_SELECTOR_CONTRACT_VERSION,
                    }
                ).encode()
            ).hexdigest()
            if output["output_key"] != expected or row["output_key"] != expected:
                raise ValueError("workflow output identity mismatch")
            output_keys.add(expected)
            selector_keys.add(selector_key)
            selected_endpoints[(row["variant"], selector["selected_endpoint"])] += 1
            variant_counts[row["variant"]] += 1
        except Exception as exc:
            failures.append(f"{identity}: {exc}")

    expected_variants = set(manifest["variants"])
    if set(variant_counts) != expected_variants:
        failures.append("manifest variants and output variants differ")
    for variant in expected_variants:
        if variant_counts[variant] != manifest["disagreement_rows"]:
            failures.append(f"{variant} does not cover every disagreement row")
    if len(output_keys) != manifest["unique_endpoint_label_inputs"] * len(expected_variants):
        failures.append("unexpected unique output-key count")
    result = {
        "outputs": len(manifest["outputs"]),
        "row_variant_counts": dict(sorted(variant_counts.items())),
        "unique_outputs": len(output_keys),
        "unique_selectors": len(selector_keys),
        "unique_neutral_plans": len(plan_keys),
        "unique_neutral_checks": len(method_check_keys),
        "unique_direct_control_checks": len(control_check_keys),
        "fail_closed_outputs": fail_closed_outputs,
        "selected_endpoints": {
            f"{variant}:{endpoint}": count
            for (variant, endpoint), count in sorted(selected_endpoints.items())
        },
        "validation_failures": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
