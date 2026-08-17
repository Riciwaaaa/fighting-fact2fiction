"""Packets and contracts for precommitment-plus-stability arbitration."""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any, Mapping, Sequence

from .cache import assert_no_secrets, canonical_json
from .contracts import ContractError, extract_json_object
from .labels import deterministic_majority

STRESS_ARBITER_PACKET_VERSION = 1
STRESS_ARBITER_CONTRACT_VERSION = "rag-stress-arbiter-v1"
_FIELDS = {
    "action",
    "confidence",
    "internal_reliability",
    "rag_stability",
    "influence_concentration",
    "decisive_signal",
    "rationale",
}


def parse_stress_arbiter(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        fields = set(value) if isinstance(value, Mapping) else set()
        raise ContractError(
            "Stress arbiter fields mismatch; "
            f"missing={sorted(_FIELDS-fields)}, extra={sorted(fields-_FIELDS)}"
        )
    if value["action"] not in {"trust_rag", "trust_memory", "keep_champion"}:
        raise ContractError("Invalid stress arbiter action")
    confidence = value["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ContractError("confidence must be numeric")
    confidence = float(confidence)
    if not 0 <= confidence <= 1:
        raise ContractError("confidence must be in [0, 1]")
    if value["internal_reliability"] not in {"reliable", "uncertain", "unreliable"}:
        raise ContractError("Invalid internal_reliability")
    if value["rag_stability"] not in {
        "robust",
        "split",
        "unstable",
        "not_observed",
    }:
        raise ContractError("Invalid rag_stability")
    if value["influence_concentration"] not in {
        "distributed",
        "concentrated",
        "unclear",
        "not_observed",
    }:
        raise ContractError("Invalid influence_concentration")
    result = {
        "action": value["action"],
        "confidence": confidence,
        "internal_reliability": value["internal_reliability"],
        "rag_stability": value["rag_stability"],
        "influence_concentration": value["influence_concentration"],
    }
    for field in ("decisive_signal", "rationale"):
        text = value[field]
        if not isinstance(text, str) or not text.strip():
            raise ContractError(f"{field} must be a non-empty string")
        result[field] = text.strip()
    return result


def parse_stress_arbiter_text(text: str) -> dict[str, Any]:
    return parse_stress_arbiter(extract_json_object(text))


def champion_prediction(row: Mapping[str, Any]) -> str:
    direction = row["counter_loose_label"]
    endpoints = (row["rag_prediction"], row["memory_prediction"])
    if direction in {"Supported", "Refuted"} and sum(
        direction == endpoint for endpoint in endpoints
    ) == 1:
        return str(direction)
    return str(row["cascade_prediction"])


def stress_relation(label: str, *, rag: str, memory: str) -> str:
    if label == rag:
        return "matches_rag"
    if label == memory:
        return "matches_memory"
    return "matches_neither_endpoint"


def compact_internal_record(
    samples: Sequence[Mapping[str, Any]], *, memory_prediction: str
) -> dict[str, Any]:
    majority = deterministic_majority(sample["verdict"] for sample in samples)
    if majority != memory_prediction:
        raise ValueError("Sealed internal samples do not reproduce memory endpoint")
    return {
        "majority_label": majority,
        "vote_counts": dict(sorted(Counter(sample["verdict"] for sample in samples).items())),
        "samples": [
            {
                "verdict": sample["verdict"],
                "confidence": sample["confidence"],
                "knowledge_basis": sample["knowledge_basis"],
                "decisive_propositions": list(sample["decisive_propositions"]),
                "premise_concerns": list(sample["premise_concerns"]),
                "rationale": sample["rationale"],
            }
            for sample in samples
        ],
    }


def build_stress_arbiter_packet(
    *,
    variant: str,
    claim: str,
    claim_date: str,
    neutral_claim_plan: Mapping[str, Any],
    rag_prediction: str,
    memory_prediction: str,
    champion: str,
    internal_samples: Sequence[Mapping[str, Any]],
    original_rag_confidence: float,
    original_answered_count: int,
    original_question_count: int,
    stress_views: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if variant not in {"control", "full"}:
        raise ValueError("variant must be control or full")
    if {rag_prediction, memory_prediction} - {"Supported", "Refuted"}:
        raise ValueError("Stress arbiter requires two binary endpoints")
    if rag_prediction == memory_prediction or champion not in {rag_prediction, memory_prediction}:
        raise ValueError("Endpoint/champion labels are inconsistent")
    visible = {
        "claim": claim,
        "claim_date": claim_date,
        "pre_retrieval_claim_plan": dict(neutral_claim_plan),
        "endpoint_labels": {
            "rag": rag_prediction,
            "memory": memory_prediction,
            "current_champion": champion,
        },
        "sealed_internal_record": compact_internal_record(
            internal_samples, memory_prediction=memory_prediction
        ),
        "original_rag_process": {
            "confidence": float(original_rag_confidence),
            "answered_count": int(original_answered_count),
            "question_count": int(original_question_count),
        },
        "stress_test_record": {"status": "withheld_matched_control", "views": []},
    }
    if variant == "full":
        rendered_views = []
        for view in sorted(stress_views, key=lambda item: item["view_type"]):
            verdict = str(view["verdict"])
            rendered_views.append(
                {
                    "view_type": view["view_type"],
                    "retained_unit_ids": list(view["retained_unit_ids"]),
                    "removed_unit_ids": list(view["removed_unit_ids"]),
                    "retained_document_count": int(view["retained_document_count"]),
                    "removed_document_count": int(view["removed_document_count"]),
                    "verdict": verdict,
                    "endpoint_relation": stress_relation(
                        verdict, rag=rag_prediction, memory=memory_prediction
                    ),
                    "confidence": float(view["confidence"]),
                    "answered_count": int(view["answered_count"]),
                    "question_count": int(view["question_count"]),
                }
            )
        visible["stress_test_record"] = {
            "status": "observed",
            "assertion_units": list(stress_views[0]["unit_structure"]),
            "views": rendered_views,
        }
    packet_key = hashlib.sha256(
        canonical_json(
            {
                "packet_version": STRESS_ARBITER_PACKET_VERSION,
                "variant": variant,
                "visible": visible,
            }
        ).encode()
    ).hexdigest()
    packet = {
        "packet_schema_version": STRESS_ARBITER_PACKET_VERSION,
        "packet_key": packet_key,
        "variant": variant,
        "visible": visible,
    }
    assert_no_secrets(packet, "rag_stress_arbiter_packet")
    return packet
