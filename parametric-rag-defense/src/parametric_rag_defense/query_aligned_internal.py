"""Contracts and identities for replaying RAG questions without retrieval."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from .cache import canonical_json
from .contracts import ContractError, extract_json_object

REPLAY_CONTRACT_VERSION = "query-aligned-internal-replay-v1"
CONFLICT_MAP_CONTRACT_VERSION = "query-aligned-answer-conflict-v1"


def replay_case_key(
    *, model_id: str, claim_id: int, claim_date: str, questions: Sequence[str]
) -> str:
    payload = {
        "contract_version": REPLAY_CONTRACT_VERSION,
        "model_id": model_id,
        "claim_id": int(claim_id),
        "claim_date": str(claim_date),
        "questions": [str(value).strip() for value in questions],
    }
    if not payload["questions"] or any(not value for value in payload["questions"]):
        raise ValueError("Replay questions must be non-empty")
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def parse_internal_question_answers(
    text: str, *, expected_questions: int
) -> dict[str, Any]:
    value = extract_json_object(text)
    if set(value) != {"answers"} or not isinstance(value["answers"], list):
        raise ContractError("Replay output must contain only an answers list")
    if len(value["answers"]) != expected_questions:
        raise ContractError(
            f"Expected {expected_questions} replay answers, received {len(value['answers'])}"
        )
    normalized = []
    for index, item in enumerate(value["answers"]):
        if not isinstance(item, Mapping) or set(item) != {
            "question_index",
            "status",
            "answer",
            "confidence",
        }:
            raise ContractError(f"Replay answer {index} has invalid fields")
        if item["question_index"] != index:
            raise ContractError(f"Replay answer {index} has a mismatched question_index")
        status = item["status"]
        if status not in {"known", "unknown"}:
            raise ContractError(f"Replay answer {index} has invalid status")
        answer = item["answer"]
        if status == "known":
            if not isinstance(answer, str) or not answer.strip():
                raise ContractError(f"Replay answer {index} requires non-empty answer")
            answer = answer.strip()
        elif answer is not None:
            raise ContractError(f"Replay answer {index} must use null when unknown")
        confidence = item["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ContractError(f"Replay answer {index} confidence must be numeric")
        confidence = float(confidence)
        if not 0 <= confidence <= 1:
            raise ContractError(f"Replay answer {index} confidence must be in [0, 1]")
        normalized.append(
            {
                "question_index": index,
                "status": status,
                "answer": answer,
                "confidence": confidence,
            }
        )
    return {"answers": normalized}


def parse_question_conflict_map(text: str, *, expected_questions: int) -> dict[str, Any]:
    value = extract_json_object(text)
    if set(value) != {"comparisons"} or not isinstance(value["comparisons"], list):
        raise ContractError("Conflict map must contain only a comparisons list")
    # Some endpoints append a single empty JSON list after otherwise complete indexed entries.
    # It carries no semantic content and is removed before strict coverage validation.
    comparisons = [item for item in value["comparisons"] if item != []]
    if len(comparisons) != expected_questions:
        raise ContractError(
            f"Expected {expected_questions} comparisons, received {len(comparisons)}"
        )
    normalized = []
    for index, item in enumerate(comparisons):
        if not isinstance(item, Mapping) or set(item) != {
            "question_index",
            "internal_state",
            "relation",
            "note",
        }:
            raise ContractError(f"Conflict comparison {index} has invalid fields")
        if item["question_index"] != index:
            raise ContractError(f"Conflict comparison {index} has mismatched question_index")
        if item["internal_state"] not in {"stable", "unstable", "unknown"}:
            raise ContractError(f"Conflict comparison {index} has invalid internal_state")
        if item["relation"] not in {"agrees", "contradicts", "compatible", "unclear"}:
            raise ContractError(f"Conflict comparison {index} has invalid relation")
        note = item["note"]
        if not isinstance(note, str) or not note.strip():
            raise ContractError(f"Conflict comparison {index} requires a note")
        # Only a stable internal answer is eligible for conflict localization. Normalize any
        # relation attached to unstable/unknown attempts to the predeclared fail-closed value.
        relation = item["relation"] if item["internal_state"] == "stable" else "unclear"
        normalized.append(
            {
                "question_index": index,
                "internal_state": item["internal_state"],
                "relation": relation,
                "note": note.strip(),
            }
        )
    return {"comparisons": normalized}


def eligible_conflict_indices(
    conflict_map: Mapping[str, Any], trace: Mapping[str, Any]
) -> list[int]:
    """Return stable contradictions whose RAG answer cites an existing passage."""

    comparisons = conflict_map.get("comparisons")
    answers = trace.get("answers", {}).get("answers")
    retrievals = trace.get("retrievals")
    if not isinstance(comparisons, list) or not isinstance(answers, list) or not isinstance(
        retrievals, list
    ):
        raise ValueError("Conflict map and trace are missing aligned question records")
    if len(comparisons) != len(answers) or len(answers) != len(retrievals):
        raise ValueError("Conflict map and trace question records do not align")
    eligible = []
    for index, (comparison, answer, group) in enumerate(
        zip(comparisons, answers, retrievals)
    ):
        if comparison.get("question_index") != index or answer.get("question_index") != index:
            raise ValueError(f"Question index mismatch at {index}")
        if comparison.get("internal_state") != "stable" or comparison.get("relation") != "contradicts":
            continue
        rank = answer.get("selected_rank")
        if rank is None:
            continue
        if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= len(group):
            raise ValueError(f"Invalid selected rank at question {index}: {rank}")
        eligible.append(index)
    return eligible


def suspect_document_ids(
    conflict_map: Mapping[str, Any], trace: Mapping[str, Any]
) -> set[str]:
    """Resolve eligible conflicts to anonymous document identities in the existing trace."""

    answers = trace["answers"]["answers"]
    retrievals = trace["retrievals"]
    return {
        str(retrievals[index][answers[index]["selected_rank"] - 1]["document_id"])
        for index in eligible_conflict_indices(conflict_map, trace)
    }


def filter_suspect_documents(
    retrievals: Sequence[Sequence[Mapping[str, Any]]], suspect_ids: set[str]
) -> list[list[dict[str, Any]]]:
    """Remove suspect identities globally from fixed retrieval groups without backfill."""

    if not suspect_ids:
        raise ValueError("At least one suspect document identity is required")
    filtered = [
        [dict(item) for item in group if str(item["document_id"]) not in suspect_ids]
        for group in retrievals
    ]
    remaining_ids = {
        str(item["document_id"]) for group in filtered for item in group
    }
    if remaining_ids & suspect_ids:
        raise AssertionError("Suspect document survived global removal")
    return filtered


def localized_conflict_gate(*, stable_questions: int, conflict_questions: int) -> bool:
    """Require repeated but localized internal/RAG contradiction.

    A single contradiction is treated as semantic-comparison noise. A conflict covering more than
    one third of stable answers is treated as broad endpoint disagreement rather than evidence that
    a small retrieved context component caused the error.
    """

    if stable_questions < 0 or conflict_questions < 0 or conflict_questions > stable_questions:
        raise ValueError("Invalid stable/conflict question counts")
    if stable_questions == 0:
        return False
    return conflict_questions >= 2 and conflict_questions * 3 <= stable_questions
