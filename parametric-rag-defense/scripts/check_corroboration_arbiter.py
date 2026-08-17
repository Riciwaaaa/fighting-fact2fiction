#!/usr/bin/env python3
"""Audit corroboration-arbiter scope, reconstruction, isolation, and contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from build_stage2_packets import internal_lookup
from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.cache import canonical_json
from parametric_rag_defense.corroboration_arbiter import (
    CORROBORATION_ARBITER_CONTRACT_VERSION,
    build_corroboration_packet,
    parse_corroboration_arbiter_text,
)
from parametric_rag_defense.workflow_runtime import prompt_version, render

_ORIGIN = re.compile(r"\b(?:clean|poison):\d+\b", re.IGNORECASE)
_URL = re.compile(r"https?://\S*", re.IGNORECASE)


def identity(row: dict[str, Any]) -> tuple[str, int, str]:
    return (
        str(row["victim_model_id"]),
        int(row["claim_id"]),
        str(row["condition_id"]),
    )


def read_cache(root: Path, key: str) -> dict[str, Any]:
    path = root / "entries" / key[:2] / f"{key}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("key") != key:
        raise ValueError("Cache key mismatch")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--counter-root",
        type=Path,
        default=Path("artifacts/runs/counter_retrieval/counter_retrieval_signal_v2"),
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("artifacts/runs/corroboration_arbiter/corroboration_arbiter_v1"),
    )
    parser.add_argument("--require-outputs", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    args.output = args.output or args.run_root / (
        "audit.json" if args.require_outputs else "packet_audit.json"
    )

    config = json.loads(args.config.read_text(encoding="utf-8"))
    manifest = json.loads((args.run_root / "private_manifest.json").read_text(encoding="utf-8"))
    counter = json.loads(
        (args.counter_root / "private_manifest.json").read_text(encoding="utf-8")
    )
    expected = {identity(row): row for row in counter["rows"]}
    observed = {identity(row): row for row in manifest["rows"]}
    failures = []
    if set(expected) != set(observed):
        failures.append(
            f"scope mismatch missing={len(set(expected)-set(observed))} "
            f"unexpected={len(set(observed)-set(expected))}"
        )
    if len(observed) != len(manifest["rows"]):
        failures.append("duplicate manifest identities")
    if manifest.get("failures"):
        failures.append(f"runtime manifest has {len(manifest['failures'])} failures")
    if args.require_outputs and manifest.get("completed_outputs") != len(expected):
        failures.append("output count incomplete")

    samples, _ = internal_lookup(
        config,
        Path("artifacts/runs/stage1/development/internal_endpoint"),
        Path(config["cache_root"]),
    )
    models = {model["id"]: model for model in config["models"] if model.get("enabled")}
    template, version = prompt_version(
        Path("prompts/corroboration_arbiter_v1.md"), "corroboration_arbiter_v1"
    )
    cache_root = Path(config["cache_root"])
    cache_keys = set()
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    action_counts = {}
    for row_id, row in observed.items():
        try:
            source_packet = json.loads(
                Path(row["source_packet_path"]).read_text(encoding="utf-8")
            )
            original_output = json.loads(
                Path(row["source_output_path"]).read_text(encoding="utf-8")
            )
            counter_output = json.loads(
                Path(row["counter_output_path"]).read_text(encoding="utf-8")
            )
            endpoint = json.loads(Path(row["endpoint_path"]).read_text(encoding="utf-8"))
            packet = json.loads(Path(row["packet_path"]).read_text(encoding="utf-8"))
            model_id, claim_id, condition_id = row_id
            reconstructed = build_corroboration_packet(
                claim=source_packet["visible"]["claim"],
                claim_date=source_packet["visible"]["claim_date"],
                neutral_claim_plan=source_packet["visible"]["neutral_claim_plan"],
                rag_prediction=row["rag_prediction"],
                memory_prediction=row["memory_prediction"],
                internal_samples=samples[model_id][claim_id],
                rag_judgment=endpoint["judgment"],
                original_evidence_judgment=original_output["judgment"],
                counter_evidence_judgment=counter_output["judgment"],
                source_packet_key=source_packet["packet_key"],
                counter_packet_key=expected[row_id]["counter_packet_key"],
            )
            if packet != reconstructed or packet["packet_key"] != row["packet_key"]:
                raise ValueError("packet reconstruction mismatch")
            prompt = render(
                template,
                {
                    "ARBITRATION_PACKET": json.dumps(
                        packet["visible"], ensure_ascii=False, sort_keys=True, indent=2
                    )
                },
            )
            if (
                (condition_id != "clean" and condition_id in prompt)
                or model_id in prompt
                or _ORIGIN.search(prompt)
                or _URL.search(prompt)
            ):
                raise ValueError("private identifier, origin, or URL leaked into prompt")

            if args.require_outputs:
                output = json.loads(Path(row["output_path"]).read_text(encoding="utf-8"))
                if output["packet_key"] != packet["packet_key"]:
                    raise ValueError("output packet mismatch")
                if output["contract_version"] != CORROBORATION_ARBITER_CONTRACT_VERSION:
                    raise ValueError("contract version mismatch")
                expected_key = hashlib.sha256(
                    canonical_json(
                        {
                            "packet_key": packet["packet_key"],
                            "arbiter_cache_key": output["arbiter_cache_key"],
                            "contract_version": CORROBORATION_ARBITER_CONTRACT_VERSION,
                        }
                    ).encode()
                ).hexdigest()
                if output["output_key"] != expected_key:
                    raise ValueError("output identity mismatch")
                entry = read_cache(cache_root, output["arbiter_cache_key"])
                parsed = parse_corroboration_arbiter_text(entry["response"]["raw_text"])
                if parsed != output["judgment"]:
                    raise ValueError("cached response and output judgment differ")
                request = entry["request"]
                if request["model"] != models[model_id]["model"]:
                    raise ValueError("arbiter is not same-model")
                if request["stage"] != "corroboration_arbiter_v1":
                    raise ValueError("arbiter stage mismatch")
                if not request["prompt_version"].startswith(version):
                    raise ValueError("prompt version mismatch")
                if request["messages"][0] != {"role": "user", "content": prompt}:
                    raise ValueError("prompt reconstruction mismatch")
                if any(
                    message.get("role") != "user"
                    or "Format-repair attempt" not in message.get("content", "")
                    for message in request["messages"][1:]
                ):
                    raise ValueError("unexpected retry message")
                action = parsed["action"]
                action_counts[action] = action_counts.get(action, 0) + 1
                if output["arbiter_cache_key"] not in cache_keys:
                    cache_keys.add(output["arbiter_cache_key"])
                    call_usage = entry["response"].get("usage") or {}
                    for key in usage:
                        usage[key] += int(call_usage.get(key) or 0)
        except Exception as exc:
            failures.append(
                f"row model={row_id[0]} claim={row_id[1]} condition={row_id[2]}: "
                f"{type(exc).__name__}: {exc}"
            )
    audit = {
        "audit_schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "phase": "outputs" if args.require_outputs else "packets",
        "expected_rows": len(expected),
        "observed_rows": len(observed),
        "unique_cache_entries": len(cache_keys),
        "action_counts": dict(sorted(action_counts.items())),
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
