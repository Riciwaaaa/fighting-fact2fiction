"""Origin-hidden passage packets and contracts for evidence-signal characterization."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

from .cache import assert_no_secrets, canonical_json
from .contracts import ContractError, extract_json_object, validate_rag_judgment
from .stage2_packets import validate_visible_packet

EVIDENCE_PACKET_SCHEMA_VERSION = 1
EVIDENCE_MAP_CONTRACT_VERSION = "evidence-passage-map-v1.1-cluster-subset"

_EVIDENCE_PREFIX = re.compile(r"^\[evidence_q\d+_r\d+\]\s*")
_MAP_FIELDS = {"passage_assessments", "content_clusters", "overall_assessment"}
_PASSAGE_FIELDS = {
    "passage_id",
    "stance",
    "directness",
    "key_assertion",
    "quality_concern",
}
_CLUSTER_FIELDS = {
    "cluster_id",
    "passage_ids",
    "shared_assertion",
    "stance",
    "directness",
}
_OVERALL_FIELDS = {
    "direction",
    "direct_support_cluster_ids",
    "direct_refutation_cluster_ids",
    "evidence_conflict",
    "summary",
}
_STANCES = {"supports", "refutes", "context", "irrelevant", "ambiguous"}
_DIRECTNESS = {"direct", "indirect", "none"}
_QUALITY_CONCERNS = {
    "none",
    "unsupported_assertion",
    "opinion_or_commentary",
    "internal_inconsistency",
    "off_topic",
    "insufficient_context",
}
_DIRECTIONS = {"supports", "refutes", "mixed", "insufficient"}


def _exact_fields(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise ContractError(
            f"{name} fields mismatch; missing={sorted(expected-set(value))}, "
            f"extra={sorted(set(value)-expected)}"
        )


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    return value.strip()


def _enum(value: Any, allowed: set[str], field: str) -> str:
    text = _text(value, field)
    if text not in allowed:
        raise ContractError(f"{field} must be one of {sorted(allowed)}")
    return text


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ContractError(f"{field} must be a list")
    result = [_text(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ContractError(f"{field} must not contain duplicates")
    return result


def parse_evidence_map(
    value: Any, *, expected_passage_ids: set[str] | None = None
) -> dict[str, Any]:
    """Validate a passage-complete evidence map."""

    if not isinstance(value, Mapping):
        raise ContractError("Evidence map response must be an object")
    _exact_fields(value, _MAP_FIELDS, "Evidence map")
    assessments_value = value["passage_assessments"]
    clusters_value = value["content_clusters"]
    overall_value = value["overall_assessment"]
    if not isinstance(assessments_value, list) or not assessments_value:
        raise ContractError("passage_assessments must be a non-empty list")
    if not isinstance(clusters_value, list) or not clusters_value:
        raise ContractError("content_clusters must be a non-empty list")
    if not isinstance(overall_value, Mapping):
        raise ContractError("overall_assessment must be an object")

    assessments: list[dict[str, Any]] = []
    assessed_ids: list[str] = []
    for index, item in enumerate(assessments_value):
        if not isinstance(item, Mapping):
            raise ContractError(f"passage_assessments[{index}] must be an object")
        _exact_fields(item, _PASSAGE_FIELDS, f"passage_assessments[{index}]")
        passage_id = _text(item["passage_id"], f"passage_assessments[{index}].passage_id")
        assessed_ids.append(passage_id)
        assessments.append(
            {
                "passage_id": passage_id,
                "stance": _enum(
                    item["stance"], _STANCES, f"passage_assessments[{index}].stance"
                ),
                "directness": _enum(
                    item["directness"],
                    _DIRECTNESS,
                    f"passage_assessments[{index}].directness",
                ),
                "key_assertion": _text(
                    item["key_assertion"], f"passage_assessments[{index}].key_assertion"
                ),
                "quality_concern": _enum(
                    item["quality_concern"],
                    _QUALITY_CONCERNS,
                    f"passage_assessments[{index}].quality_concern",
                ),
            }
        )
    if len(assessed_ids) != len(set(assessed_ids)):
        raise ContractError("Each passage_id must have exactly one passage assessment")
    assessed_set = set(assessed_ids)
    if expected_passage_ids is not None and assessed_set != expected_passage_ids:
        raise ContractError(
            "Passage assessment coverage mismatch; "
            f"missing={sorted(expected_passage_ids-assessed_set)}, "
            f"extra={sorted(assessed_set-expected_passage_ids)}"
        )

    clusters: list[dict[str, Any]] = []
    cluster_ids: list[str] = []
    clustered_passage_ids: list[str] = []
    for index, item in enumerate(clusters_value):
        if not isinstance(item, Mapping):
            raise ContractError(f"content_clusters[{index}] must be an object")
        _exact_fields(item, _CLUSTER_FIELDS, f"content_clusters[{index}]")
        cluster_id = _text(item["cluster_id"], f"content_clusters[{index}].cluster_id")
        passage_ids = _string_list(
            item["passage_ids"], f"content_clusters[{index}].passage_ids"
        )
        if not passage_ids:
            raise ContractError(f"content_clusters[{index}].passage_ids cannot be empty")
        cluster_ids.append(cluster_id)
        clustered_passage_ids.extend(passage_ids)
        clusters.append(
            {
                "cluster_id": cluster_id,
                "passage_ids": passage_ids,
                "shared_assertion": _text(
                    item["shared_assertion"], f"content_clusters[{index}].shared_assertion"
                ),
                "stance": _enum(
                    item["stance"], _STANCES, f"content_clusters[{index}].stance"
                ),
                "directness": _enum(
                    item["directness"],
                    _DIRECTNESS,
                    f"content_clusters[{index}].directness",
                ),
            }
        )
    if len(cluster_ids) != len(set(cluster_ids)):
        raise ContractError("Each cluster_id must be unique")
    if len(clustered_passage_ids) != len(set(clustered_passage_ids)):
        raise ContractError("Each passage must occur in exactly one content cluster")
    unknown_clustered_passages = set(clustered_passage_ids) - assessed_set
    if unknown_clustered_passages:
        raise ContractError(
            "Content clusters reference passages without assessments: "
            f"{sorted(unknown_clustered_passages)}"
        )

    _exact_fields(overall_value, _OVERALL_FIELDS, "overall_assessment")
    support_ids = _string_list(
        overall_value["direct_support_cluster_ids"],
        "overall_assessment.direct_support_cluster_ids",
    )
    refutation_ids = _string_list(
        overall_value["direct_refutation_cluster_ids"],
        "overall_assessment.direct_refutation_cluster_ids",
    )
    known_clusters = set(cluster_ids)
    unknown_clusters = (set(support_ids) | set(refutation_ids)) - known_clusters
    if unknown_clusters:
        raise ContractError(f"Overall assessment references unknown clusters: {unknown_clusters}")
    if set(support_ids) & set(refutation_ids):
        raise ContractError("A cluster cannot be both direct support and direct refutation")
    if not isinstance(overall_value["evidence_conflict"], bool):
        raise ContractError("overall_assessment.evidence_conflict must be boolean")
    overall = {
        "direction": _enum(
            overall_value["direction"], _DIRECTIONS, "overall_assessment.direction"
        ),
        "direct_support_cluster_ids": support_ids,
        "direct_refutation_cluster_ids": refutation_ids,
        "evidence_conflict": overall_value["evidence_conflict"],
        "summary": _text(overall_value["summary"], "overall_assessment.summary"),
    }
    return {
        "passage_assessments": assessments,
        "content_clusters": clusters,
        "overall_assessment": overall,
    }


def parse_evidence_map_text(
    text: str, *, expected_passage_ids: set[str] | None = None
) -> dict[str, Any]:
    return parse_evidence_map(
        extract_json_object(text), expected_passage_ids=expected_passage_ids
    )


def _passage_text(value: str) -> str | None:
    text = _EVIDENCE_PREFIX.sub("", value, count=1).strip()
    # Search corpora occasionally contain visual separators (for example, a row
    # made only of underscores).  They contain no proposition for the reporter
    # to assess and can force a formally invalid empty ``key_assertion``.  This
    # mechanical check is independent of endpoint predictions and gold labels.
    if not any(character.isalnum() for character in text):
        return None
    return text


def build_evidence_packet(
    *,
    claim: str,
    claim_date: str,
    rag_task_key: str,
    rag_judgment: Mapping[str, Any],
    neutral_plan: Mapping[str, Any],
    neutral_plan_cache_key: str,
    same_model_id: str,
) -> dict[str, Any]:
    """Build an endpoint-hidden packet containing every unique retrieved passage."""

    normalized = validate_rag_judgment(dict(rag_judgment))
    question_texts: list[list[str]] = []
    unique_texts: dict[str, str] = {}
    for question in normalized["questions"]:
        texts = [
            text
            for item in question["evidence"]
            if (text := _passage_text(item)) is not None
        ]
        hashes: list[str] = []
        for text in texts:
            text_hash = hashlib.sha256(text.encode()).hexdigest()
            unique_texts.setdefault(text_hash, text)
            hashes.append(text_hash)
        question_texts.append(hashes)
    if not unique_texts:
        raise ValueError("Evidence mapping requires at least one retrieved passage")

    ordered_hashes = sorted(
        unique_texts,
        key=lambda value: hashlib.sha256(
            f"evidence-map-order-v1:{rag_task_key}:{value}".encode()
        ).hexdigest(),
    )
    aliases = {text_hash: f"passage_{index:02d}" for index, text_hash in enumerate(ordered_hashes, 1)}
    questions = []
    for index, (question, hashes) in enumerate(zip(normalized["questions"], question_texts), 1):
        questions.append(
            {
                "question_id": f"question_{index:02d}",
                "question": question["question"],
                "passage_ids": list(dict.fromkeys(aliases[value] for value in hashes)),
            }
        )
    passages = [
        {"passage_id": aliases[text_hash], "text": unique_texts[text_hash]}
        for text_hash in ordered_hashes
    ]
    visible = {
        "claim": claim.strip(),
        "claim_date": claim_date or "unknown",
        "neutral_claim_plan": dict(neutral_plan),
        "retrieval_questions": questions,
        "passages": passages,
    }
    validate_visible_packet(visible)
    identity = {
        "evidence_packet_schema_version": EVIDENCE_PACKET_SCHEMA_VERSION,
        "rag_task_key": rag_task_key,
        "neutral_plan_cache_key": neutral_plan_cache_key,
        "same_model_id": same_model_id,
        "passage_text_sha256": ordered_hashes,
    }
    packet_key = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    packet = {
        "evidence_packet_schema_version": EVIDENCE_PACKET_SCHEMA_VERSION,
        "packet_key": packet_key,
        "visible": visible,
        "provenance": identity,
    }
    assert_no_secrets(packet, "evidence_signal_packet")
    return packet
