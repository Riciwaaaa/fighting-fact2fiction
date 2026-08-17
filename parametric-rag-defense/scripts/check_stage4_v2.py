#!/usr/bin/env python3
"""Audit Stage 4 v2 identity, same-model calls, contracts, and information firewalls."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from parametric_rag_defense.aligned_workflow import candidate_prediction
from parametric_rag_defense.cache import canonical_json
from parametric_rag_defense.contracts import parse_internal_judgment
from parametric_rag_defense.stage4_v2 import (
    ADJUDICATOR_CONTRACT_VERSION,
    ARCHITECT_CONTRACT_VERSION,
    parse_adjudicator,
    parse_architect,
    validate_action_verdict,
)
from parametric_rag_defense.workflow_runtime import prompt_version, render

_URL = re.compile(r"https?://", re.IGNORECASE)
_ORIGIN = re.compile(r"\b(?:clean|poison):\d+\b", re.IGNORECASE)
_FORBIDDEN = ("fact2fiction_p", "condition_id", "gold_label", "target_label")


def entry(cache_root: Path, key: str) -> dict:
    path = cache_root / "entries" / key[:2] / f"{key}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if value["key"] != key:
        raise ValueError(f"cache key mismatch: {key}")
    return value


def assert_prompt_safe(text: str, role: str) -> None:
    if _URL.search(text) or _ORIGIN.search(text):
        raise ValueError(f"{role} exposes source metadata")
    lowered = text.lower()
    for marker in _FORBIDDEN:
        if marker in lowered:
            raise ValueError(f"{role} contains forbidden marker {marker}")


def minimal_endpoint_packet(packet: dict) -> dict:
    """Reconstruct the selector's allow-listed endpoint fields for an exact audit."""

    retrieval = packet["visible"]["retrieval_assessment"]
    memory = packet["visible"]["memory_only_assessment"]
    return {
        "retrieval": {
            "verdict": retrieval["verdict"],
            "confidence": retrieval["confidence"],
            "coverage": retrieval["coverage"],
        },
        "memory": {
            "leading_verdicts": memory["leading_verdicts"],
            "verdict_distribution": memory["verdict_distribution"],
            "agreement_fraction": memory["agreement_fraction"],
            "mean_confidence": memory["mean_confidence"],
            "knowledge_basis_distribution": memory["knowledge_basis_distribution"],
            "repeat_count": memory["repeat_count"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=Path("artifacts/runs/stage4/stage4_same_model_v2"))
    parser.add_argument("--stage1-config", type=Path, default=Path("configs/stage1_matrix.json"))
    args = parser.parse_args()
    config = json.loads(args.stage1_config.read_text(encoding="utf-8"))
    model_names = {model["id"]: model["model"] for model in config["models"]}
    cache_root = Path(config["cache_root"])
    manifest = json.loads((args.run_root / "private_manifest.json").read_text(encoding="utf-8"))
    selector_template, selector_version = prompt_version(
        Path("prompts/stage4_firewalled_selector_v2.md"),
        "stage4_firewalled_selector_v2",
    )
    failures = []
    if manifest["failures"]:
        failures.append(f"manifest retains {len(manifest['failures'])} failures")
    if len(manifest["outputs"]) != manifest["target_disagreements"]:
        failures.append("output count differs from target disagreements")
    identities = set()
    output_keys = set()
    role_keys: dict[str, set[str]] = {
        "architect": set(),
        "factual_check": set(),
        "synthesis": set(),
        "selector": set(),
    }
    actions = Counter()
    role_references = Counter()
    for row in manifest["outputs"]:
        identity = (row["claim_id"], row["victim_model_id"], row["condition_id"])
        if identity in identities:
            failures.append(f"duplicate identity: {identity}")
        identities.add(identity)
        try:
            packet = json.loads(Path(row["aligned_packet_path"]).read_text(encoding="utf-8"))
            router = json.loads(Path(row["router_output_path"]).read_text(encoding="utf-8"))
            output = json.loads(Path(row["output_path"]).read_text(encoding="utf-8"))
            if packet["packet_key"] != row["aligned_packet_key"] or output["aligned_packet_key"] != row["aligned_packet_key"]:
                raise ValueError("aligned packet identity mismatch")
            if router["output_key"] != row["router_output_key"] or output["router_output_key"] != row["router_output_key"]:
                raise ValueError("router identity mismatch")
            model_id = row["victim_model_id"]
            if packet["provenance"]["same_model_id"] != model_id:
                raise ValueError("packet same-model identity mismatch")
            retrieval_verdict = packet["visible"]["retrieval_assessment"]["verdict"]
            memory_verdict = candidate_prediction(packet["visible"]["memory_only_assessment"])
            if retrieval_verdict == memory_verdict:
                raise ValueError("v2 output exists for endpoint agreement")

            architecture = output["architect"]
            if manifest["mode"] == "proposition":
                plan = parse_architect(architecture["judgment"])
                architect_key = architecture["cache_key"]
                role_keys["architect"].add(architect_key)
                role_references["architect"] += 1
                architect_entry = entry(cache_root, architect_key)
                if architect_entry["request"]["model"] != model_names[model_id]:
                    raise ValueError("architect uses wrong model")
                assert_prompt_safe(canonical_json(architect_entry["request"]["messages"]), "architect")
            else:
                if architecture is not None:
                    raise ValueError("direct control unexpectedly has architect")
                plan = None
                architect_key = None

            factual_keys = []
            for check in output["factual_checks"]:
                parse_internal_judgment(canonical_json(check["judgment"]))
                key = check["cache_key"]
                factual_keys.append(key)
                role_keys["factual_check"].add(key)
                role_references["factual_check"] += 1
                check_entry = entry(cache_root, key)
                if check_entry["request"]["model"] != model_names[model_id]:
                    raise ValueError("factual check uses wrong model")
                messages = canonical_json(check_entry["request"]["messages"])
                assert_prompt_safe(messages, "factual check")
                retrieval_rationale = packet["visible"]["retrieval_assessment"]["rationale"]
                if retrieval_rationale in messages:
                    raise ValueError("factual check exposes retrieval rationale")
                for sample in packet["visible"]["memory_only_assessment"]["samples"]:
                    if sample["rationale"] in messages:
                        raise ValueError("factual check exposes memory endpoint rationale")

            synthesis = output["internal_synthesis"]
            synthesis_judgment = parse_internal_judgment(canonical_json(synthesis["judgment"]))
            synthesis_key = synthesis["cache_key"]
            role_keys["synthesis"].add(synthesis_key)
            role_references["synthesis"] += 1
            synthesis_entry = entry(cache_root, synthesis_key)
            if synthesis_entry["request"]["model"] != model_names[model_id]:
                raise ValueError("synthesis uses wrong model")
            synthesis_messages = canonical_json(synthesis_entry["request"]["messages"])
            assert_prompt_safe(synthesis_messages, "synthesis")
            if packet["visible"]["retrieval_assessment"]["rationale"] in synthesis_messages:
                raise ValueError("synthesis exposes retrieval rationale")
            if router["router"]["judgment"]["assessment"] in synthesis_messages:
                raise ValueError("synthesis exposes router assessment")

            final = parse_adjudicator(output["adjudicator"]["judgment"])
            validate_action_verdict(
                final,
                retrieval_verdict=retrieval_verdict,
                memory_verdict=memory_verdict,
                internal_verdict=synthesis_judgment["verdict"],
            )
            if output["derived_prediction"] != final["verdict"] or row["prediction"] != final["verdict"]:
                raise ValueError("derived prediction mismatch")
            final_key = output["adjudicator"]["cache_key"]
            role_keys["selector"].add(final_key)
            role_references["selector"] += 1
            final_entry = entry(cache_root, final_key)
            if final_entry["request"]["model"] != model_names[model_id]:
                raise ValueError("selector uses wrong model")
            final_messages = canonical_json(final_entry["request"]["messages"])
            assert_prompt_safe(final_messages, "selector")
            expected_prompt = render(
                selector_template,
                {
                    "CLAIM": packet["visible"]["claim"],
                    "CLAIM_DATE": packet["visible"]["claim_date"],
                    "MINIMAL_ENDPOINTS": json.dumps(
                        minimal_endpoint_packet(packet),
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    ),
                    "INTERNAL_SYNTHESIS": json.dumps(
                        synthesis["judgment"],
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    ),
                },
            )
            if final_entry["request"]["prompt_version"] != selector_version:
                raise ValueError("selector prompt version mismatch")
            if final_entry["request"]["messages"] != [{"role": "user", "content": expected_prompt}]:
                raise ValueError("selector prompt differs from its exact information allow-list")

            expected = hashlib.sha256(
                canonical_json(
                    {
                        "mode": manifest["mode"],
                        "aligned_packet_key": packet["packet_key"],
                        "router_output_key": router["output_key"],
                        "architect_cache_key": architect_key,
                        "factual_check_cache_keys": factual_keys,
                        "synthesis_cache_key": synthesis_key,
                        "final_cache_key": final_key,
                        "architect_contract": ARCHITECT_CONTRACT_VERSION if plan is not None else None,
                        "adjudicator_contract": ADJUDICATOR_CONTRACT_VERSION,
                    }
                ).encode()
            ).hexdigest()
            if output["output_key"] != expected or row["output_key"] != expected:
                raise ValueError("output identity mismatch")
            output_keys.add(expected)
            actions[final["action"]] += 1
        except Exception as exc:
            failures.append(f"{identity}: {exc}")

    if len(output_keys) != len(manifest["outputs"]):
        failures.append("output keys are not unique")
    expected_role_counts = {
        "architect": manifest["target_disagreements"] if manifest["mode"] == "proposition" else 0,
        "factual_check": manifest["target_disagreements"] * (4 if manifest["mode"] == "proposition" else 5),
        "synthesis": manifest["target_disagreements"],
        "selector": manifest["target_disagreements"],
    }
    for role, expected in expected_role_counts.items():
        if role_references[role] != expected:
            failures.append(f"{role} reference count {role_references[role]} != {expected}")
        if len(role_keys[role]) > expected:
            failures.append(f"{role} unique key count exceeds its reference count")
    result = {
        "mode": manifest["mode"],
        "outputs": len(manifest["outputs"]),
        "unique_keys_by_role": {key: len(value) for key, value in role_keys.items()},
        "references_by_role": dict(sorted(role_references.items())),
        "actions": dict(sorted(actions.items())),
        "validation_failures": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
