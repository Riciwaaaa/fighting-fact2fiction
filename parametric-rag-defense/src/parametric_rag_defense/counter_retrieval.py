"""Origin-hidden leave-original-document-out retrieval and evidence packets."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Sequence

from .cache import assert_no_secrets, canonical_json
from .stage2_packets import validate_visible_packet

COUNTER_PACKET_SCHEMA_VERSION = 1
_URL = re.compile(r"https?://\S*", re.IGNORECASE)


def mask_urls(value: str) -> str:
    return _URL.sub("[URL]", value)


def retrieve_excluding(
    query_embeddings: Any,
    resources: Sequence[Mapping[str, Any]],
    embeddings: Any,
    *,
    excluded_document_ids: set[str],
    excluded_text_sha256: set[str],
    top_k: int = 5,
) -> list[list[dict[str, Any]]]:
    """Retrieve fresh documents per query after document and exact-text exclusion.

    New documents are globally deduplicated across query order, matching the Stage 1 RAG adapter.
    Exclusion is based only on observable document identity and exact content, never origin.
    """

    import numpy as np

    if top_k < 1:
        raise ValueError("top_k must be positive")
    matrix = np.asarray(embeddings, dtype="float32")
    queries = np.asarray(query_embeddings, dtype="float32")
    if matrix.ndim != 2 or queries.ndim != 2 or matrix.shape[1] != queries.shape[1]:
        raise ValueError("Embedding matrices must be two-dimensional with matching width")
    if len(resources) != matrix.shape[0]:
        raise ValueError("Resource/embedding row mismatch")
    seen = set(excluded_document_ids)
    results: list[list[dict[str, Any]]] = []
    for query in queries:
        distances = np.sum((matrix - query) ** 2, axis=1)
        candidates = []
        for index in np.argsort(distances):
            resource = dict(resources[int(index)])
            document_id = str(resource["document_id"])
            text = str(resource["text"])
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if (
                document_id in excluded_document_ids
                or text_hash in excluded_text_sha256
                or not text.strip()
            ):
                continue
            candidates.append(
                {
                    **resource,
                    "rank": len(candidates) + 1,
                    "distance": float(distances[int(index)]),
                    "text_sha256": text_hash,
                }
            )
            if len(candidates) == top_k:
                break
        selected = [item for item in candidates if item["document_id"] not in seen]
        seen.update(item["document_id"] for item in selected)
        results.append(selected)
    return results


def build_counter_packet(
    *,
    claim: str,
    claim_date: str,
    neutral_plan: Mapping[str, Any],
    questions: Sequence[str],
    retrievals: Sequence[Sequence[Mapping[str, Any]]],
    source_rag_task_key: str,
    source_packet_key: str,
    same_model_id: str,
    excluded_document_count: int,
    excluded_text_sha256: Sequence[str],
    evidence_chars: int = 300,
) -> dict[str, Any]:
    """Build an endpoint-hidden packet from counter-retrieved documents."""

    if len(questions) != len(retrievals) or not questions:
        raise ValueError("Questions and counter retrieval groups must align and be non-empty")
    if evidence_chars < 1:
        raise ValueError("evidence_chars must be positive")
    question_hashes: list[list[str]] = []
    unique_texts: dict[str, str] = {}
    for group in retrievals:
        hashes = []
        for item in group:
            text = mask_urls(str(item["text"])[:evidence_chars]).strip()
            if not any(character.isalnum() for character in text):
                continue
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            unique_texts.setdefault(text_hash, text)
            hashes.append(text_hash)
        question_hashes.append(hashes)
    if not unique_texts:
        raise ValueError("Counter retrieval produced no visible passages")
    ordered_hashes = sorted(
        unique_texts,
        key=lambda value: hashlib.sha256(
            f"counter-map-order-v1:{source_rag_task_key}:{value}".encode()
        ).hexdigest(),
    )
    aliases = {
        text_hash: f"passage_{index:02d}"
        for index, text_hash in enumerate(ordered_hashes, 1)
    }
    visible = {
        "claim": mask_urls(claim.strip()),
        "claim_date": mask_urls(claim_date or "unknown"),
        "neutral_claim_plan": dict(neutral_plan),
        "retrieval_questions": [
            {
                "question_id": f"question_{index:02d}",
                "question": mask_urls(str(question).strip()),
                "passage_ids": list(
                    dict.fromkeys(aliases[value] for value in hashes)
                ),
            }
            for index, (question, hashes) in enumerate(
                zip(questions, question_hashes), 1
            )
        ],
        "passages": [
            {"passage_id": aliases[text_hash], "text": unique_texts[text_hash]}
            for text_hash in ordered_hashes
        ],
    }
    validate_visible_packet(visible)
    provenance = {
        "counter_packet_schema_version": COUNTER_PACKET_SCHEMA_VERSION,
        "source_rag_task_key": source_rag_task_key,
        "source_packet_key": source_packet_key,
        "same_model_id": same_model_id,
        "exclusion_policy": "all-original-documents-and-exact-text-stage1-no-backfill-v2",
        "excluded_document_count": excluded_document_count,
        "excluded_text_sha256": sorted(set(excluded_text_sha256)),
        "counter_passage_text_sha256": ordered_hashes,
    }
    packet_key = hashlib.sha256(canonical_json(provenance).encode()).hexdigest()
    packet = {
        "counter_packet_schema_version": COUNTER_PACKET_SCHEMA_VERSION,
        "packet_key": packet_key,
        "visible": visible,
        "provenance": provenance,
    }
    assert_no_secrets(packet, "counter_retrieval_packet")
    return packet
