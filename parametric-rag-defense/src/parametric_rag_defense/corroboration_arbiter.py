"""Packet construction and contracts for corroboration-aware endpoint arbitration."""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any, Mapping

from .cache import canonical_json
from .contracts import ContractError, extract_json_object
from .labels import deterministic_majority

CORROBORATION_PACKET_SCHEMA_VERSION = 1
CORROBORATION_ARBITER_CONTRACT_VERSION = "corroboration-arbiter-v1"
ARBITER_FIELDS = {
    "action",
    "confidence",
    "independent_evidence_assessment",
    "internal_knowledge_assessment",
    "cross_view_assessment",
    "pivotal_fact",
    "rationale",
}


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


def parse_corroboration_arbiter(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError("Corroboration arbiter response must be an object")
    if set(value) != ARBITER_FIELDS:
        raise ContractError(
            "Corroboration arbiter fields mismatch; "
            f"missing={sorted(ARBITER_FIELDS-set(value))}, "
            f"extra={sorted(set(value)-ARBITER_FIELDS)}"
        )
    if value["action"] not in {"trust_rag", "trust_memory", "escalate"}:
        raise ContractError(f"Invalid action: {value['action']!r}")
    if value["independent_evidence_assessment"] not in {
        "supports_rag",
        "supports_memory",
        "conflicting",
        "unresolved",
    }:
        raise ContractError("Invalid independent_evidence_assessment")
    if value["internal_knowledge_assessment"] not in {
        "reliable",
        "uncertain",
        "unreliable",
    }:
        raise ContractError("Invalid internal_knowledge_assessment")
    if value["cross_view_assessment"] not in {
        "corroborated",
        "contradicted",
        "complementary",
        "unresolved",
    }:
        raise ContractError("Invalid cross_view_assessment")
    return {
        "action": value["action"],
        "confidence": _confidence(value["confidence"]),
        "independent_evidence_assessment": value[
            "independent_evidence_assessment"
        ],
        "internal_knowledge_assessment": value["internal_knowledge_assessment"],
        "cross_view_assessment": value["cross_view_assessment"],
        "pivotal_fact": _text(value["pivotal_fact"], "pivotal_fact"),
        "rationale": _text(value["rationale"], "rationale"),
    }


def parse_corroboration_arbiter_text(text: str) -> dict[str, Any]:
    return parse_corroboration_arbiter(extract_json_object(text))


def compact_evidence_report(judgment: Mapping[str, Any]) -> dict[str, Any]:
    passages = list(judgment["passage_assessments"])
    stance_counts = Counter(item["stance"] for item in passages)
    direct_stance_counts = Counter(
        item["stance"] for item in passages if item["directness"] == "direct"
    )
    quality_counts = Counter(item["quality_concern"] for item in passages)
    return {
        "overall_assessment": judgment["overall_assessment"],
        "content_clusters": list(judgment["content_clusters"]),
        "summary_statistics": {
            "unique_passage_count": len(passages),
            "stance_counts": dict(sorted(stance_counts.items())),
            "direct_stance_counts": dict(sorted(direct_stance_counts.items())),
            "quality_concern_counts": dict(sorted(quality_counts.items())),
        },
    }


def build_corroboration_packet(
    *,
    claim: str,
    claim_date: str,
    neutral_claim_plan: Mapping[str, Any],
    rag_prediction: str,
    memory_prediction: str,
    internal_samples: list[Mapping[str, Any]],
    rag_judgment: Mapping[str, Any],
    original_evidence_judgment: Mapping[str, Any],
    counter_evidence_judgment: Mapping[str, Any],
    source_packet_key: str,
    counter_packet_key: str,
) -> dict[str, Any]:
    if rag_prediction == memory_prediction:
        raise ValueError("Corroboration packet requires endpoint disagreement")
    majority = deterministic_majority(sample["verdict"] for sample in internal_samples)
    if majority != memory_prediction:
        raise ValueError("Memory endpoint is inconsistent with its internal samples")
    questions = list(rag_judgment["questions"])
    visible = {
        "claim": claim,
        "claim_date": claim_date,
        "neutral_claim_plan": dict(neutral_claim_plan),
        "endpoint_labels": {"rag": rag_prediction, "memory": memory_prediction},
        "closed_book_assessments": {
            "majority_label": majority,
            "vote_counts": dict(
                sorted(Counter(sample["verdict"] for sample in internal_samples).items())
            ),
            "samples": [
                {
                    "verdict": sample["verdict"],
                    "confidence": sample["confidence"],
                    "knowledge_basis": sample["knowledge_basis"],
                    "premise_concerns": list(sample["premise_concerns"]),
                    "decisive_propositions": list(sample["decisive_propositions"]),
                    "rationale": sample["rationale"],
                }
                for sample in internal_samples
            ],
        },
        "rag_process": {
            "confidence": rag_judgment["confidence"],
            "question_count": len(questions),
            "answered_count": sum(item["status"] == "answered" for item in questions),
            "unanswered_count": sum(item["status"] == "none" for item in questions),
            "dropped_count": sum(item["status"] == "dropped" for item in questions),
        },
        "original_evidence_report": compact_evidence_report(
            original_evidence_judgment
        ),
        "leave_original_out_evidence_report": compact_evidence_report(
            counter_evidence_judgment
        ),
    }
    provenance = {
        "source_packet_key": source_packet_key,
        "counter_packet_key": counter_packet_key,
    }
    packet_key = hashlib.sha256(
        canonical_json(
            {
                "packet_schema_version": CORROBORATION_PACKET_SCHEMA_VERSION,
                "visible": visible,
                "provenance": provenance,
            }
        ).encode()
    ).hexdigest()
    return {
        "packet_schema_version": CORROBORATION_PACKET_SCHEMA_VERSION,
        "packet_key": packet_key,
        "visible": visible,
        "provenance": provenance,
    }
