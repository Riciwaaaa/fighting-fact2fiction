"""Contracts and packet construction for strictly same-model RAG arbitration."""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any, Mapping

from .cache import canonical_json
from .contracts import ContractError, VERDICTS, extract_json_object, validate_rag_judgment
from .stage2_packets import validate_visible_packet

ALIGNED_PACKET_SCHEMA_VERSION = 1
ALIGNED_ROUTER_CONTRACT_VERSION = "aligned-router-v1.1-format-alias"
ALIGNED_FINAL_CONTRACT_VERSION = "aligned-final-v1"

ROUTER_FIELDS = {
    "route",
    "provisional_endpoint",
    "confidence",
    "decisive_conflict",
    "pivotal_proposition",
    "assessment",
}
FINAL_FIELDS = {
    "selected_endpoint",
    "confidence",
    "decisive_conflict",
    "proposition_check_assessment",
    "rationale",
}


def _exact_fields(value: Mapping[str, Any], required: set[str], name: str) -> None:
    if set(value) != required:
        raise ContractError(
            f"{name} fields mismatch; missing={sorted(required-set(value))}, "
            f"extra={sorted(set(value)-required)}"
        )


def _edit_distance(left: str, right: str) -> int:
    """Return Levenshtein distance for short JSON field names."""

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, 1):
        current = [left_index]
        for right_index, right_char in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _repair_single_field_typo(
    value: Mapping[str, Any], required: set[str], *, max_distance: int = 2
) -> dict[str, Any]:
    """Repair one unambiguous near-match key without changing any field value."""

    result = dict(value)
    missing = required - set(result)
    extra = set(result) - required
    if len(missing) != 1 or len(extra) != 1:
        return result
    missing_key = next(iter(missing))
    extra_key = next(iter(extra))
    if _edit_distance(extra_key, missing_key) <= max_distance:
        result[missing_key] = result.pop(extra_key)
    return result


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    return value.strip()


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError("confidence must be numeric")
    result = float(value)
    if not 0 <= result <= 1:
        raise ContractError("confidence must be in [0, 1]")
    return result


def parse_aligned_router(value: Any) -> dict[str, Any]:
    """Validate a router object already extracted from JSON."""

    if not isinstance(value, dict):
        raise ContractError("Aligned router response must be an object")
    value = _repair_single_field_typo(value, ROUTER_FIELDS)
    _exact_fields(value, ROUTER_FIELDS, "Aligned router")
    if value["route"] not in {"choose_retrieval", "choose_memory", "verify_proposition"}:
        raise ContractError(f"Invalid route: {value['route']!r}")
    if value["provisional_endpoint"] not in {"retrieval", "memory"}:
        raise ContractError(f"Invalid provisional_endpoint: {value['provisional_endpoint']!r}")
    return {
        "route": value["route"],
        "provisional_endpoint": value["provisional_endpoint"],
        "confidence": _confidence(value["confidence"]),
        "decisive_conflict": _text(value["decisive_conflict"], "decisive_conflict"),
        "pivotal_proposition": _text(value["pivotal_proposition"], "pivotal_proposition"),
        "assessment": _text(value["assessment"], "assessment"),
    }


def parse_aligned_router_text(text: str) -> dict[str, Any]:
    return parse_aligned_router(extract_json_object(text))


def parse_aligned_final(value: Any) -> dict[str, Any]:
    """Validate the Stage C endpoint-selection object."""

    if not isinstance(value, dict):
        raise ContractError("Aligned final response must be an object")
    _exact_fields(value, FINAL_FIELDS, "Aligned final arbiter")
    if value["selected_endpoint"] not in {"retrieval", "memory"}:
        raise ContractError(f"Invalid selected_endpoint: {value['selected_endpoint']!r}")
    return {
        "selected_endpoint": value["selected_endpoint"],
        "confidence": _confidence(value["confidence"]),
        "decisive_conflict": _text(value["decisive_conflict"], "decisive_conflict"),
        "proposition_check_assessment": _text(
            value["proposition_check_assessment"], "proposition_check_assessment"
        ),
        "rationale": _text(value["rationale"], "rationale"),
    }


def parse_aligned_final_text(text: str) -> dict[str, Any]:
    return parse_aligned_final(extract_json_object(text))


def candidate_prediction(candidate: Mapping[str, Any]) -> str | None:
    leaders = candidate["leading_verdicts"]
    if not isinstance(leaders, list) or len(leaders) != 1:
        return None
    prediction = leaders[0]
    return prediction if prediction in VERDICTS else None


def same_model_candidate(packet: Mapping[str, Any], model_id: str) -> dict[str, Any]:
    """Return only the candidate produced by the RAG victim's own model."""

    alias = next(
        (
            candidate_alias
            for candidate_alias, candidate_model in packet["provenance"][
                "internal_candidate_map"
            ].items()
            if candidate_model == model_id
        ),
        None,
    )
    if alias is None:
        raise ValueError(f"Packet has no internal candidate for {model_id}")
    candidate = next(
        (
            value
            for value in packet["visible"]["memory_only_assessments"]
            if value["candidate_id"] == alias
        ),
        None,
    )
    if candidate is None:
        raise ValueError(f"Packet candidate alias is absent: {alias}")
    return {key: child for key, child in candidate.items() if key != "candidate_id"}


def endpoint_retrieval_view(judgment: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only the RAG endpoint decision for Variant A."""

    normalized = validate_rag_judgment(dict(judgment))
    statuses = Counter(question["status"] for question in normalized["questions"])
    return {
        "verdict": normalized["verdict"],
        "confidence": normalized["confidence"],
        "rationale": normalized["justification"],
        "coverage": {
            "question_count": len(normalized["questions"]),
            "answered_count": statuses["answered"],
            "unanswered_count": statuses["none"],
            "dropped_count": statuses["dropped"],
        },
    }


def evidence_retrieval_view(judgment: Mapping[str, Any]) -> dict[str, Any]:
    """Expose every normalized top-k excerpt without source identity for Variant B."""

    normalized = validate_rag_judgment(dict(judgment))
    result = endpoint_retrieval_view(normalized)
    result["questions"] = [
        {
            "question": question["question"],
            "status": question["status"],
            "answer": question["answer"],
            "retrieved_excerpts": list(question["evidence"]),
        }
        for question in normalized["questions"]
    ]
    return result


def build_aligned_packet(
    *,
    source_packet: Mapping[str, Any],
    rag_judgment: Mapping[str, Any],
    model_id: str,
    variant: str,
) -> dict[str, Any]:
    """Build an inference-visible packet with exactly one model in all three roles."""

    if variant not in {"endpoint_only", "evidence_aware"}:
        raise ValueError(f"Unknown aligned packet variant: {variant}")
    memory = same_model_candidate(source_packet, model_id)
    retrieval = (
        endpoint_retrieval_view(rag_judgment)
        if variant == "endpoint_only"
        else evidence_retrieval_view(rag_judgment)
    )
    visible = {
        "claim": source_packet["visible"]["claim"],
        "claim_date": source_packet["visible"]["claim_date"],
        "retrieval_assessment": retrieval,
        "memory_only_assessment": memory,
    }
    validate_visible_packet(visible)
    identity = {
        "aligned_packet_schema_version": ALIGNED_PACKET_SCHEMA_VERSION,
        "source_packet_key": source_packet["packet_key"],
        "rag_task_key": source_packet["provenance"]["rag_task_key"],
        "internal_cache_keys": source_packet["provenance"]["internal_cache_keys"][model_id],
        "same_model_id": model_id,
        "variant": variant,
    }
    packet_key = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    return {
        "aligned_packet_schema_version": ALIGNED_PACKET_SCHEMA_VERSION,
        "packet_key": packet_key,
        "visible": visible,
        "provenance": identity,
    }


def selected_prediction(packet: Mapping[str, Any], endpoint: str) -> str | None:
    if endpoint == "retrieval":
        return packet["visible"]["retrieval_assessment"]["verdict"]
    if endpoint == "memory":
        return candidate_prediction(packet["visible"]["memory_only_assessment"])
    raise ValueError(f"Unknown endpoint: {endpoint}")
