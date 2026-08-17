"""Deterministic assertion-cluster stress views over a fixed RAG retrieval."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Sequence

from .cache import canonical_json
from .contracts import ContractError, extract_json_object

STRESS_VIEW_VERSION = "fixed-assertion-cluster-stress-v1"
_EVIDENCE_PREFIX = re.compile(r"^\[evidence_q\d+_r\d+\]\s*")


def _visible_evidence_text(value: str) -> str:
    text = _EVIDENCE_PREFIX.sub("", value, count=1).strip()
    if not text:
        raise ValueError("Visible evidence text cannot be empty")
    return text


def parse_stress_answers(
    text: str, *, result_counts: list[int], base_parser: Any
) -> dict[str, Any]:
    """Parse answers with a fail-closed adapter for an orphan rank on a null answer.

    A few models emit ``status=none`` and ``answer=null`` while leaving a non-null selected rank.
    An unanswered item cannot select evidence, so discard only that orphan rank before applying
    the unchanged Stage 1 answer contract. Every other malformed field still fails.
    """

    try:
        return base_parser(text, result_counts)
    except ContractError as original:
        value = extract_json_object(text)
        answers = value.get("answers")
        if not isinstance(answers, list):
            raise original
        changed = False
        normalized = []
        for item in answers:
            if not isinstance(item, dict):
                raise original
            current = dict(item)
            if (
                current.get("status") == "none"
                and current.get("answer") is None
                and current.get("selected_rank") is not None
            ):
                current["selected_rank"] = None
                changed = True
            normalized.append(current)
        if not changed:
            raise original
        return base_parser(canonical_json({"answers": normalized}), result_counts)


def passage_document_map(
    *,
    packet_visible: Mapping[str, Any],
    endpoint_judgment: Mapping[str, Any],
    trace: Mapping[str, Any],
) -> dict[str, set[str]]:
    """Map every visible passage alias to all indistinguishable trace document IDs.

    The evidence mapper saw the 300-character, URL-masked endpoint excerpts. Distinct documents
    with the same visible excerpt were deliberately collapsed there, so they remain inseparable
    here and are assigned to the same alias.
    """

    passages = packet_visible.get("passages")
    packet_questions = packet_visible.get("retrieval_questions")
    endpoint_questions = endpoint_judgment.get("questions")
    retrievals = trace.get("retrievals")
    if not all(isinstance(value, list) for value in (
        passages,
        packet_questions,
        endpoint_questions,
        retrievals,
    )):
        raise ValueError("Packet, endpoint, or trace lacks aligned evidence records")
    if not (len(packet_questions) == len(endpoint_questions) == len(retrievals)):
        raise ValueError("Packet, endpoint, and trace question counts differ")

    text_to_alias: dict[str, str] = {}
    for item in passages:
        alias = str(item["passage_id"])
        text = str(item["text"]).strip()
        if not alias or not text or text in text_to_alias:
            raise ValueError("Packet passage aliases and texts must be unique and non-empty")
        text_to_alias[text] = alias
    alias_documents = {alias: set() for alias in text_to_alias.values()}

    for question_index, (packet_question, endpoint_question, group) in enumerate(
        zip(packet_questions, endpoint_questions, retrievals)
    ):
        evidence = endpoint_question.get("evidence")
        if not isinstance(evidence, list) or len(evidence) != len(group):
            raise ValueError(f"Endpoint/trace evidence count mismatch at question {question_index}")
        aliases = []
        for rendered, trace_item in zip(evidence, group):
            text = _visible_evidence_text(str(rendered))
            try:
                alias = text_to_alias[text]
            except KeyError as exc:
                raise ValueError(
                    f"Endpoint excerpt is absent from packet at question {question_index}"
                ) from exc
            aliases.append(alias)
            alias_documents[alias].add(str(trace_item["document_id"]))
        if list(dict.fromkeys(aliases)) != list(packet_question.get("passage_ids", [])):
            raise ValueError(f"Packet alias order mismatch at question {question_index}")

    if any(not identifiers for identifiers in alias_documents.values()):
        raise ValueError("At least one packet passage could not be resolved to a document")
    return alias_documents


def assertion_units(
    *, evidence_judgment: Mapping[str, Any], alias_documents: Mapping[str, set[str]]
) -> list[dict[str, Any]]:
    """Return content clusters plus singleton units for passages omitted from clustering."""

    known_aliases = set(alias_documents)
    used: set[str] = set()
    units = []
    for cluster in evidence_judgment["content_clusters"]:
        aliases = [str(value) for value in cluster["passage_ids"]]
        if not aliases or len(aliases) != len(set(aliases)):
            raise ValueError("A content cluster must contain unique passage aliases")
        if set(aliases) - known_aliases or used & set(aliases):
            raise ValueError("Content clusters contain unknown or repeated passage aliases")
        used.update(aliases)
        units.append(
            {
                "unit_id": str(cluster["cluster_id"]),
                "kind": "content_cluster",
                "passage_ids": aliases,
                "document_ids": sorted(
                    {identifier for alias in aliases for identifier in alias_documents[alias]}
                ),
                "stance": str(cluster["stance"]),
                "directness": str(cluster["directness"]),
                "shared_assertion": str(cluster["shared_assertion"]),
            }
        )
    for alias in sorted(known_aliases - used):
        units.append(
            {
                "unit_id": f"unclustered::{alias}",
                "kind": "unclustered_singleton",
                "passage_ids": [alias],
                "document_ids": sorted(alias_documents[alias]),
                "stance": "unclustered",
                "directness": "unknown",
                "shared_assertion": "Withheld: passage was not assigned to a content cluster.",
            }
        )
    if not units:
        raise ValueError("At least one assertion unit is required")
    covered_documents = {value for unit in units for value in unit["document_ids"]}
    expected_documents = {value for values in alias_documents.values() for value in values}
    if covered_documents != expected_documents:
        raise ValueError("Assertion units do not cover the fixed retrieval")
    return units


def complementary_unit_halves(
    units: Sequence[Mapping[str, Any]], *, task_key: str
) -> tuple[list[str], list[str]] | None:
    """Greedily balance indivisible assertion units into deterministic disjoint halves."""

    if len(units) < 2:
        return None
    ordered = sorted(
        units,
        key=lambda unit: (
            -len(unit["document_ids"]),
            str(unit["unit_id"]),
        ),
    )
    bins: tuple[list[str], list[str]] = ([], [])
    weights = [0, 0]
    for unit in ordered:
        target = 0 if weights[0] <= weights[1] else 1
        bins[target].append(str(unit["unit_id"]))
        weights[target] += len(unit["document_ids"])
    if not bins[0] or not bins[1]:
        return None
    return bins


def dominant_aligned_cluster(
    units: Sequence[Mapping[str, Any]], *, rag_prediction: str
) -> str | None:
    """Select the largest direct assertion cluster aligned with the RAG verdict."""

    stance = {"Supported": "supports", "Refuted": "refutes"}.get(rag_prediction)
    if stance is None:
        return None
    candidates = [
        unit
        for unit in units
        if unit["kind"] == "content_cluster"
        and unit["stance"] == stance
        and unit["directness"] == "direct"
    ]
    if not candidates:
        return None
    selected = min(
        candidates,
        key=lambda unit: (-len(unit["document_ids"]), str(unit["unit_id"])),
    )
    return str(selected["unit_id"])


def filtered_retrievals(
    retrievals: Sequence[Sequence[Mapping[str, Any]]], *, retained_document_ids: set[str]
) -> list[list[dict[str, Any]]]:
    return [
        [dict(item) for item in group if str(item["document_id"]) in retained_document_ids]
        for group in retrievals
    ]


def context_key(retrievals: Sequence[Sequence[Mapping[str, Any]]]) -> str:
    groups = [[str(item["document_id"]) for item in group] for group in retrievals]
    return hashlib.sha256(canonical_json(groups).encode()).hexdigest()


def build_stress_views(
    *, task_key: str, rag_prediction: str, units: Sequence[Mapping[str, Any]],
    retrievals: Sequence[Sequence[Mapping[str, Any]]]
) -> list[dict[str, Any]]:
    """Build up to three fixed-context views without retrieval or backfill."""

    by_id = {str(unit["unit_id"]): unit for unit in units}
    if len(by_id) != len(units):
        raise ValueError("Assertion unit IDs must be unique")
    all_documents = {str(item["document_id"]) for group in retrievals for item in group}
    unit_documents = {value for unit in units for value in unit["document_ids"]}
    if all_documents != unit_documents:
        raise ValueError("Assertion units and trace retrieval documents differ")

    specifications: list[tuple[str, set[str], list[str]]] = []
    halves = complementary_unit_halves(units, task_key=task_key)
    if halves is not None:
        for view_type, retained_units in zip(("half_a", "half_b"), halves):
            retained = {
                value for unit_id in retained_units for value in by_id[unit_id]["document_ids"]
            }
            specifications.append((view_type, retained, retained_units))

    dominant = dominant_aligned_cluster(units, rag_prediction=rag_prediction)
    if dominant is not None:
        retained = all_documents - set(by_id[dominant]["document_ids"])
        if retained:
            specifications.append(
                (
                    "dominant_aligned_cluster_removed",
                    retained,
                    [unit_id for unit_id in by_id if unit_id != dominant],
                )
            )

    views = []
    for view_type, retained_ids, retained_units in specifications:
        filtered = filtered_retrievals(retrievals, retained_document_ids=retained_ids)
        if not any(filtered):
            continue
        views.append(
            {
                "view_type": view_type,
                "retained_unit_ids": sorted(retained_units),
                "removed_unit_ids": sorted(set(by_id) - set(retained_units)),
                "retained_document_ids": sorted(retained_ids),
                "removed_document_ids": sorted(all_documents - retained_ids),
                "retrievals": filtered,
                "context_key": context_key(filtered),
            }
        )
    return views
