#!/usr/bin/env python3
"""Audit evidence-signal scope, prompt isolation, cache integrity, and output contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import canonical_json
from parametric_rag_defense.evidence_signals import parse_evidence_map, parse_evidence_map_text
from parametric_rag_defense.neutral_firewall import parse_neutral_plan
from parametric_rag_defense.stage2_packets import validate_visible_packet
from parametric_rag_defense.workflow_runtime import prompt_version, render
from run_evidence_signal import DEFAULT_CONDITIONS, disagreement_scope

_ORIGIN = re.compile(r"\b(?:clean|poison):\d+\b", re.IGNORECASE)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)


def read_cache(cache_root: Path, key: str) -> dict[str, Any]:
    path = cache_root / "entries" / key[:2] / f"{key}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("key") != key:
        raise ValueError(f"Cache key mismatch: {path}")
    if not isinstance(value.get("request"), dict) or not isinstance(value.get("response"), dict):
        raise ValueError(f"Malformed cache entry: {path}")
    return value


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--freeze", type=Path, default=Path("configs/evidence_signal_v1_freeze.json")
    )
    parser.add_argument(
        "--amendment",
        type=Path,
        default=Path("configs/evidence_signal_v1_amendment_1.json"),
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        help="Optional single confirmation protocol whose frozen_sha256 replaces freeze/amendment",
    )
    parser.add_argument(
        "--protocol-amendment",
        type=Path,
        help="Optional confirmation amendment whose updated_sha256 overrides frozen digests",
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("artifacts/runs/evidence_signal/evidence_signal_v1"),
    )
    parser.add_argument(
        "--conditions",
        default=",".join(DEFAULT_CONDITIONS),
        help="Comma-separated condition scope to reconstruct.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    args.output = args.output or args.run_root / "audit.json"

    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.protocol:
        protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
        frozen_digests = dict(protocol["frozen_sha256"])
        if args.protocol_amendment:
            protocol_amendment = json.loads(
                args.protocol_amendment.read_text(encoding="utf-8")
            )
            frozen_digests.update(protocol_amendment["updated_sha256"])
    else:
        freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
        amendment = json.loads(args.amendment.read_text(encoding="utf-8"))
        frozen_digests = {
            **freeze["frozen_sha256"],
            **amendment["updated_sha256"],
        }
    manifest = json.loads((args.run_root / "private_manifest.json").read_text(encoding="utf-8"))
    model_configs = {
        model["id"]: model
        for model in config["models"]
        if model.get("enabled") and "rag_victim" in model["roles"] and "arbiter" in model["roles"]
    }
    expected_rows, expected_cases = disagreement_scope(
        config=config,
        requested_models=set(model_configs),
        requested_conditions={value for value in args.conditions.split(",") if value},
        selected_claims=None,
    )
    expected_identities = {
        (row["victim_model_id"], int(row["claim_id"]), row["condition_id"])
        for row in expected_rows
    }
    observed_identities = {
        (row["victim_model_id"], int(row["claim_id"]), row["condition_id"])
        for row in manifest["rows"]
    }
    failures: list[str] = []
    if manifest.get("failures"):
        failures.append(f"runtime manifest contains {len(manifest['failures'])} failures")
    if expected_identities != observed_identities:
        failures.append(
            "scope mismatch: "
            f"missing={len(expected_identities-observed_identities)} "
            f"unexpected={len(observed_identities-expected_identities)}"
        )
    if len(manifest["rows"]) != len(observed_identities):
        failures.append("manifest contains duplicate row identities")
    if manifest.get("completed_plans") != len(expected_cases):
        failures.append("completed plan count does not match expected unique cases")

    for path_text, expected_digest in frozen_digests.items():
        path = Path(path_text)
        observed_digest = sha256_path(path)
        if observed_digest != expected_digest:
            failures.append(
                f"frozen digest mismatch {path}: expected={expected_digest} observed={observed_digest}"
            )

    plan_template, plan_version = prompt_version(
        Path("prompts/neutral_claim_plan_v1.md"), "neutral_claim_plan_v1"
    )
    evidence_template, evidence_version = prompt_version(
        Path("prompts/evidence_passage_map_v1.md"), "evidence_passage_map_v1"
    )
    cache_root = Path(config["cache_root"])
    unique_cache_keys: set[str] = set()
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    plan_keys_by_case: dict[str, str] = {}
    output_keys: set[str] = set()
    for row in manifest["rows"]:
        try:
            packet_path = Path(row["packet_path"])
            output_path = Path(row["output_path"])
            endpoint_path = Path(row["endpoint_path"])
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            output = json.loads(output_path.read_text(encoding="utf-8"))
            endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
            if endpoint["task_key"] != row["rag_task_key"]:
                raise ValueError("endpoint task key mismatch")
            if packet["provenance"]["rag_task_key"] != row["rag_task_key"]:
                raise ValueError("packet RAG task key mismatch")
            if packet["provenance"]["same_model_id"] != row["victim_model_id"]:
                raise ValueError("packet same-model provenance mismatch")
            if output["packet_key"] != packet["packet_key"]:
                raise ValueError("output packet key mismatch")
            if output["output_key"] in output_keys:
                raise ValueError("duplicate immutable output key")
            output_keys.add(output["output_key"])
            expected_output_key = hashlib.sha256(
                canonical_json(
                    {
                        "packet_key": packet["packet_key"],
                        "evidence_cache_key": output["evidence_cache_key"],
                        "contract_version": output["contract_version"],
                    }
                ).encode()
            ).hexdigest()
            if output["output_key"] != expected_output_key:
                raise ValueError("derived output key mismatch")
            validate_visible_packet(packet["visible"])
            passage_ids = {
                passage["passage_id"] for passage in packet["visible"]["passages"]
            }
            if len(passage_ids) != len(packet["visible"]["passages"]):
                raise ValueError("packet passage aliases are not unique")
            parse_evidence_map(output["judgment"], expected_passage_ids=passage_ids)

            plan_key = output["plan_cache_key"]
            existing_plan_key = plan_keys_by_case.setdefault(row["case_key"], plan_key)
            if existing_plan_key != plan_key:
                raise ValueError("one model/claim case has multiple claim plans")
            plan_entry = read_cache(cache_root, plan_key)
            evidence_entry = read_cache(cache_root, output["evidence_cache_key"])
            plan_judgment = parse_neutral_plan(plan_entry["response"]["parsed"])
            if plan_judgment != packet["visible"]["neutral_claim_plan"]:
                raise ValueError("packet neutral plan differs from cached parsed plan")
            parse_evidence_map_text(
                evidence_entry["response"]["raw_text"], expected_passage_ids=passage_ids
            )
            model = model_configs[row["victim_model_id"]]
            expected_plan_prompt = render(
                plan_template,
                {
                    "CLAIM": packet["visible"]["claim"],
                    "CLAIM_DATE": packet["visible"]["claim_date"],
                },
            )
            expected_evidence_prompt = render(
                evidence_template,
                {
                    "EVIDENCE_PACKET": json.dumps(
                        packet["visible"], ensure_ascii=False, sort_keys=True, indent=2
                    )
                },
            )
            plan_request = plan_entry["request"]
            evidence_request = evidence_entry["request"]
            if plan_request["model"] != model["model"] or evidence_request["model"] != model["model"]:
                raise ValueError("same-model request mismatch")
            if not plan_request["prompt_version"].startswith(plan_version):
                raise ValueError("claim-plan prompt version mismatch")
            if not evidence_request["prompt_version"].startswith(evidence_version):
                raise ValueError("evidence-map prompt version mismatch")
            if not plan_request["messages"] or plan_request["messages"][0] != {
                "role": "user",
                "content": expected_plan_prompt,
            }:
                raise ValueError("claim-plan prompt reconstruction mismatch")
            if not evidence_request["messages"] or evidence_request["messages"][0] != {
                "role": "user",
                "content": expected_evidence_prompt,
            }:
                raise ValueError("evidence-map prompt reconstruction mismatch")
            if any(
                message.get("role") != "user"
                or "Format-repair attempt" not in message.get("content", "")
                for message in plan_request["messages"][1:]
            ):
                raise ValueError("unexpected claim-plan retry message")
            if any(
                message.get("role") != "user"
                or "Evidence-map format repair" not in message.get("content", "")
                for message in evidence_request["messages"][1:]
            ):
                raise ValueError("unexpected evidence-map retry message")
            if evidence_request["stage"] != "evidence_signal_passage_map_v1":
                raise ValueError("unexpected evidence-map stage")
            prompt_text = "\n".join(
                message["content"] for message in evidence_request["messages"]
            )
            leaked_attack_condition = (
                row["condition_id"] != "clean" and row["condition_id"] in prompt_text
            )
            if leaked_attack_condition or row["victim_model_id"] in prompt_text:
                raise ValueError("private condition/model identifier leaked into evidence prompt")
            if _ORIGIN.search(prompt_text) or _URL.search(prompt_text):
                raise ValueError("origin identifier or raw URL leaked into evidence prompt")
            for key, entry in ((plan_key, plan_entry), (output["evidence_cache_key"], evidence_entry)):
                if key in unique_cache_keys:
                    continue
                unique_cache_keys.add(key)
                call_usage = entry["response"].get("usage") or {}
                for field in usage:
                    usage[field] += int(call_usage.get(field) or 0)
        except Exception as exc:
            failures.append(
                f"row model={row.get('victim_model_id')} claim={row.get('claim_id')} "
                f"condition={row.get('condition_id')}: {type(exc).__name__}: {exc}"
            )

    audit = {
        "audit_schema_version": 1,
        "experiment_id": manifest.get("experiment_id"),
        "expected_rows": len(expected_rows),
        "observed_rows": len(manifest["rows"]),
        "expected_unique_cases": len(expected_cases),
        "observed_unique_plan_cases": len(plan_keys_by_case),
        "unique_cache_entries": len(unique_cache_keys),
        "referenced_usage": usage,
        "failures": failures,
        "status": "passed" if not failures else "failed",
    }
    atomic_json(args.output, audit)
    print(json.dumps(audit, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
