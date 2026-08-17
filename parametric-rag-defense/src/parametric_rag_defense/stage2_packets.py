"""Gold-isolated, identity-masked packets for Stage 2 analysis and Stage 3 inference."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from .cache import assert_no_secrets, canonical_json
from .contracts import parse_internal_judgment, validate_rag_judgment

PACKET_SCHEMA_VERSION = 1
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_ORIGIN_ID = re.compile(r"\b(?:clean|poison):\d+\b", re.IGNORECASE)
_FORBIDDEN_KEY_TOKENS = {
    "attack",
    "audit",
    "condition",
    "correct",
    "gold",
    "label",
    "model",
    "poison",
    "provider",
    "seed",
    "source",
    "split",
    "task",
    "url",
}


class Stage2PacketError(RuntimeError):
    """Raised when an inference-visible packet could leak evaluation or endpoint identity."""


def _key_tokens(key: str) -> set[str]:
    return {part for part in re.split(r"[^a-z0-9]+", key.lower()) if part}


def _mask_urls(value: Any) -> Any:
    if isinstance(value, str):
        return _URL.sub("[URL]", value)
    if isinstance(value, list):
        return [_mask_urls(item) for item in value]
    if isinstance(value, dict):
        return {key: _mask_urls(child) for key, child in value.items()}
    return value


def validate_visible_packet(value: Any, path: str = "visible") -> None:
    """Reject fields and string markers that must never enter an arbiter prompt."""

    if isinstance(value, dict):
        for key, child in value.items():
            forbidden = _key_tokens(str(key)) & _FORBIDDEN_KEY_TOKENS
            if forbidden:
                raise Stage2PacketError(
                    f"Inference-visible key is forbidden at {path}.{key}: {sorted(forbidden)}"
                )
            validate_visible_packet(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_visible_packet(child, f"{path}[{index}]")
    elif isinstance(value, str):
        if _URL.search(value):
            raise Stage2PacketError(f"Raw URL is forbidden at {path}")
        if _ORIGIN_ID.search(value):
            raise Stage2PacketError(f"Source-origin identifier is forbidden at {path}")


def _selected_evidence(question: Mapping[str, Any]) -> list[str]:
    evidence = list(question["evidence"])
    if not evidence:
        return []
    selected_rank = question["selected_rank"]
    index = selected_rank - 1 if isinstance(selected_rank, int) else 0
    if index < 0 or index >= len(evidence):
        index = 0
    return [evidence[index]]


def compact_rag_judgment(judgment: Mapping[str, Any]) -> dict[str, Any]:
    normalized = validate_rag_judgment(dict(judgment))
    status_counts = Counter(question["status"] for question in normalized["questions"])
    result = {
        "verdict": normalized["verdict"],
        "confidence": normalized["confidence"],
        "rationale": normalized["justification"],
        "coverage": {
            "question_count": len(normalized["questions"]),
            "answered_count": status_counts["answered"],
            "unanswered_count": status_counts["none"],
            "dropped_count": status_counts["dropped"],
        },
        "questions": [
            {
                "question": question["question"],
                "status": question["status"],
                "answer": question["answer"],
                "selected_evidence": _selected_evidence(question),
            }
            for question in normalized["questions"]
        ],
    }
    return _mask_urls(result)


def summarize_internal_samples(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not samples:
        raise Stage2PacketError("Each memory-only candidate requires at least one sample")
    normalized = [parse_internal_judgment(canonical_json(dict(sample))) for sample in samples]
    verdict_counts = Counter(sample["verdict"] for sample in normalized)
    basis_counts = Counter(sample["knowledge_basis"] for sample in normalized)
    leading_count = max(verdict_counts.values())
    result = {
        "repeat_count": len(normalized),
        "verdict_distribution": dict(sorted(verdict_counts.items())),
        "leading_verdicts": sorted(
            verdict for verdict, count in verdict_counts.items() if count == leading_count
        ),
        "agreement_fraction": leading_count / len(normalized),
        "mean_confidence": sum(sample["confidence"] for sample in normalized) / len(normalized),
        "knowledge_basis_distribution": dict(sorted(basis_counts.items())),
        "samples": normalized,
    }
    return _mask_urls(result)


def candidate_aliases(claim_id: int, model_ids: Sequence[str]) -> dict[str, str]:
    """Return a deterministic per-claim permutation so identity cannot become a routing shortcut."""

    ordered = sorted(
        model_ids,
        key=lambda model_id: hashlib.sha256(
            f"stage2-alias-v1:{claim_id}:{model_id}".encode()
        ).hexdigest(),
    )
    return {model_id: f"candidate_{chr(65 + index)}" for index, model_id in enumerate(ordered)}


def build_packet(
    *,
    claim_id: int,
    claim: str,
    claim_date: str,
    rag_task_key: str,
    rag_judgment: Mapping[str, Any],
    internal_samples: Mapping[str, Sequence[Mapping[str, Any]]],
    internal_cache_keys: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    model_ids = sorted(internal_samples)
    if set(model_ids) != set(internal_cache_keys):
        raise Stage2PacketError("Internal samples and cache-key model sets differ")
    aliases = candidate_aliases(claim_id, model_ids)
    memory_assessments = []
    for model_id in sorted(model_ids, key=lambda value: aliases[value]):
        assessment = summarize_internal_samples(internal_samples[model_id])
        assessment["candidate_id"] = aliases[model_id]
        memory_assessments.append(assessment)

    visible = _mask_urls(
        {
            "claim": claim.strip(),
            "claim_date": claim_date or "unknown",
            "retrieval_assessment": compact_rag_judgment(rag_judgment),
            "memory_only_assessments": memory_assessments,
        }
    )
    validate_visible_packet(visible)
    identity = {
        "packet_schema_version": PACKET_SCHEMA_VERSION,
        "rag_task_key": rag_task_key,
        "internal_cache_keys": {
            model_id: list(internal_cache_keys[model_id]) for model_id in sorted(model_ids)
        },
    }
    packet_key = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    packet = {
        "packet_schema_version": PACKET_SCHEMA_VERSION,
        "packet_key": packet_key,
        "visible": visible,
        "provenance": {
            "rag_task_key": rag_task_key,
            "internal_candidate_map": {
                aliases[model_id]: model_id for model_id in sorted(model_ids)
            },
            "internal_cache_keys": identity["internal_cache_keys"],
            "identity_masking": "deterministic per-claim permutation; only candidate aliases are visible",
        },
    }
    assert_no_secrets(packet, "stage2_packet")
    return packet


def packet_path(root: Path, packet_key: str) -> Path:
    return root / packet_key[:2] / f"{packet_key}.json"


def store_immutable(root: Path, packet: Mapping[str, Any]) -> tuple[Path, bool]:
    packet_key = str(packet["packet_key"])
    path = packet_path(root, packet_key)
    serialized = json.dumps(
        packet, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != serialized:
            raise Stage2PacketError(f"Refusing to overwrite conflicting packet: {path}")
        return path, True
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{packet_key}.", suffix=".tmp")
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
