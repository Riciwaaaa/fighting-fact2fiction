#!/usr/bin/env python3
"""Normalize old run-05 endpoints into development-only Stage 1 artifacts.

The importer strips URLs, attack labels, and gold labels from the inference artifact. Gold labels
are written to a separate evaluation-only file. Imported records retain source hashes and are never
represented as outputs from the new four-label prompt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


URL_RE = re.compile(r"https?://[^\s)\]>]+", re.IGNORECASE)


def mask_urls(value: Any) -> Any:
    """Recursively remove source identity and synthetic URL suffixes from inference data."""

    if isinstance(value, str):
        return URL_RE.sub("[SOURCE]", value).replace("/created", "[MASKED_PATH]")
    if isinstance(value, list):
        return [mask_urls(item) for item in value]
    if isinstance(value, dict):
        return {key: mask_urls(item) for key, item in value.items()}
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def normalize_label(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    labels = {
        "supported": "Supported",
        "support": "Supported",
        "refuted": "Refuted",
        "refute": "Refuted",
        "nei": "Not Enough Evidence",
        "not enough evidence": "Not Enough Evidence",
        "conflicting": "Conflicting Evidence",
        "conflicting evidence": "Conflicting Evidence",
    }
    return labels.get(text, str(value).strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-run",
        type=Path,
        default=Path("../fighting-fact2fiction-main/experiments/runs/05_mimo_100claim_fusion"),
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/legacy/run05_stage1"))
    args = parser.parse_args()

    source_run = args.source_run.resolve()
    output = args.output.resolve()
    claim_manifest_path = source_run / "claims.json"
    claim_manifest = json.loads(claim_manifest_path.read_text(encoding="utf-8"))

    endpoint_rows: list[dict[str, Any]] = []
    labels: dict[str, str] = {}
    sources: list[dict[str, Any]] = []
    missing: dict[str, list[str]] = {}

    for claim_id in claim_manifest["claim_ids"]:
        internal_path = source_run / "model_only" / f"{claim_id}.json"
        rag_path = source_run / "attacked_infact_dumps" / f"{claim_id}.json"
        absent = [str(path) for path in (internal_path, rag_path) if not path.exists()]
        if absent:
            missing[str(claim_id)] = absent
            continue

        internal = json.loads(internal_path.read_text(encoding="utf-8"))
        rag = json.loads(rag_path.read_text(encoding="utf-8"))
        endpoint_rows.append(
            {
                "artifact_schema_version": 1,
                "provenance": "legacy_run05_development_only",
                "claim_id": claim_id,
                "claim": internal["claim"],
                "claim_date": internal.get("claim_date"),
                "condition": {
                    "attack": "fact2fiction",
                    "poison_rate": rag.get("poison_rate"),
                    "attacker_model": rag.get("attacker_model"),
                },
                "internal_endpoint": {
                    "model": claim_manifest.get("model_only_model"),
                    "prompt": "legacy_binary_two_call_model_only",
                    "verdict": normalize_label(internal.get("verdict")),
                    "sub_claims": mask_urls(internal.get("sub_claims", [])),
                },
                "rag_endpoint": {
                    "model": rag.get("fact_checker_model"),
                    "verdict": normalize_label(rag.get("pred_label")),
                    "justification": mask_urls(rag.get("after_justification") or ""),
                    "questions": [
                        {
                            "question": mask_urls(item.get("question") or ""),
                            "answer": mask_urls(item.get("answer") or ""),
                            "evidence_text": mask_urls(item.get("scraped_text") or ""),
                        }
                        for item in rag.get("adopted_qa_evidence", [])
                    ],
                },
            }
        )
        labels[str(claim_id)] = normalize_label(internal.get("gold_label")) or ""
        for role, path in (("internal", internal_path), ("rag", rag_path)):
            sources.append(
                {
                    "claim_id": claim_id,
                    "role": role,
                    "path": str(path),
                    "sha256": sha256(path),
                }
            )

    endpoint_rows.sort(key=lambda row: row["claim_id"])
    sources.sort(key=lambda row: (row["claim_id"], row["role"]))
    atomic_jsonl(output / "endpoints.jsonl", endpoint_rows)
    atomic_json(
        output / "evaluation_labels.json",
        {
            "warning": "EVALUATION ONLY: never join this file into an inference prompt",
            "labels": labels,
        },
    )
    atomic_json(
        output / "manifest.json",
        {
            "artifact_schema_version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "provenance": "legacy_run05_development_only",
            "source_run": str(source_run),
            "source_manifest": {
                "path": str(claim_manifest_path),
                "sha256": sha256(claim_manifest_path),
            },
            "records": len(endpoint_rows),
            "missing": missing,
            "source_files": sources,
            "safety": {
                "raw_urls_removed": True,
                "is_fake_removed_from_inference": True,
                "gold_labels_separated": True,
                "eligible_for_locked_test": False,
            },
        },
    )
    print(f"Imported {len(endpoint_rows)} legacy endpoint pairs into {output}")
    if missing:
        print(f"Missing endpoint pairs: {sorted(missing, key=int)}")


if __name__ == "__main__":
    main()
