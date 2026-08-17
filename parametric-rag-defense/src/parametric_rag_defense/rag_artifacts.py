"""Normalized, immutable Stage 1 RAG artifact storage."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .cache import assert_no_secrets, canonical_json
from .contracts import ContractError, validate_rag_judgment

RAG_ARTIFACT_SCHEMA_VERSION = 1
_URL = re.compile(r"https?://", re.IGNORECASE)
_ORIGIN_ID = re.compile(r"\b(?:clean|poison):\d+\b", re.IGNORECASE)
_FORBIDDEN_GOLD_KEYS = {"gold", "gold_label", "target_label", "correct_label"}


class RAGArtifactError(RuntimeError):
    """Raised when an upstream record is unsafe, inconsistent, or non-immutable."""


def _mask_urls(value: Any) -> Any:
    """Recursively enforce the declared URL firewall at the normalization boundary."""

    if isinstance(value, dict):
        return {key: _mask_urls(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_mask_urls(child) for child in value]
    if isinstance(value, str):
        return re.sub(r"https?://\S*", "[URL]", value, flags=re.IGNORECASE)
    return value


def _reject_gold(value: Any, path: str = "record") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_GOLD_KEYS:
                raise RAGArtifactError(f"Gold field is forbidden in inference artifact: {path}.{key}")
            _reject_gold(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_gold(child, f"{path}[{index}]")


def validate_audit(audit: Any, *, clean: bool) -> dict[str, Any]:
    required = {
        "clean_documents_before_injection",
        "poison_documents_injected",
        "realized_poison_fraction",
        "retrieved_documents_total",
        "retrieved_poison_documents",
    }
    if not isinstance(audit, dict) or set(audit) != required:
        fields = set(audit) if isinstance(audit, dict) else set()
        raise RAGArtifactError(
            f"audit fields mismatch; missing={sorted(required-fields)}, extra={sorted(fields-required)}"
        )
    clean_count = audit["clean_documents_before_injection"]
    injected = audit["poison_documents_injected"]
    retrieved_total = audit["retrieved_documents_total"]
    retrieved_poison = audit["retrieved_poison_documents"]
    for name, value in (
        ("clean_documents_before_injection", clean_count),
        ("poison_documents_injected", injected),
        ("retrieved_documents_total", retrieved_total),
        ("retrieved_poison_documents", retrieved_poison),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RAGArtifactError(f"audit.{name} must be a non-negative integer")
    if clean_count < 1:
        raise RAGArtifactError("audit.clean_documents_before_injection must be at least 1")
    fraction = audit["realized_poison_fraction"]
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0 <= fraction < 1:
        raise RAGArtifactError("audit.realized_poison_fraction must be in [0, 1)")
    expected_fraction = injected / (clean_count + injected)
    if abs(float(fraction) - expected_fraction) > 1e-9:
        raise RAGArtifactError(
            "audit.realized_poison_fraction disagrees with injected/(clean+injected)"
        )
    if retrieved_poison > retrieved_total or retrieved_poison > injected:
        raise RAGArtifactError("retrieved poison count is impossible")
    if clean and (injected != 0 or retrieved_poison != 0 or float(fraction) != 0):
        raise RAGArtifactError("clean task contains non-zero poisoning audit values")
    if not clean and injected < 1:
        raise RAGArtifactError("attacked task must inject at least one poison document")
    return {
        "clean_documents_before_injection": clean_count,
        "poison_documents_injected": injected,
        "realized_poison_fraction": float(fraction),
        "retrieved_documents_total": retrieved_total,
        "retrieved_poison_documents": retrieved_poison,
    }


def normalize_record(record: Any, expected_task: dict[str, Any]) -> dict[str, Any]:
    required = {"task_key", "judgment", "audit", "provenance"}
    if not isinstance(record, dict) or set(record) != required:
        fields = set(record) if isinstance(record, dict) else set()
        raise RAGArtifactError(
            f"record fields mismatch; missing={sorted(required-fields)}, extra={sorted(fields-required)}"
        )
    if record["task_key"] != expected_task["task_key"]:
        raise RAGArtifactError("record task_key does not match the expected task")
    provenance = record["provenance"]
    if not isinstance(provenance, dict) or not provenance:
        raise RAGArtifactError("provenance must be a non-empty object")
    assert_no_secrets(record, "rag_record")
    _reject_gold(record)
    try:
        judgment = validate_rag_judgment(_mask_urls(record["judgment"]))
    except ContractError as exc:
        raise RAGArtifactError(str(exc)) from exc
    if _URL.search(canonical_json(judgment)):
        raise RAGArtifactError("normalized judgment contains a raw URL; mask it before ingestion")
    if _ORIGIN_ID.search(canonical_json(judgment)):
        raise RAGArtifactError(
            "normalized judgment contains a source-origin identifier; replace it with a neutral ID"
        )
    audit = validate_audit(record["audit"], clean=expected_task["condition"]["id"] == "clean")
    return {
        "rag_artifact_schema_version": RAG_ARTIFACT_SCHEMA_VERSION,
        "task_key": expected_task["task_key"],
        "task": expected_task,
        "judgment": judgment,
        "audit": audit,
        "provenance": provenance,
    }


def artifact_path(root: Path, task_key: str) -> Path:
    return root / task_key[:2] / f"{task_key}.json"


def store_immutable(root: Path, artifact: dict[str, Any]) -> tuple[Path, bool]:
    """Store one normalized artifact; return ``(path, already_present)``."""

    task_key = artifact["task_key"]
    path = artifact_path(root, task_key)
    serialized = json.dumps(
        artifact, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != serialized:
            raise RAGArtifactError(f"Refusing to overwrite conflicting artifact: {path}")
        return path, True
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{task_key}.", suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return path, False
