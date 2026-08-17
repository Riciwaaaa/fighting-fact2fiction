"""Strict parsing and validation for structured LLM outputs."""

from __future__ import annotations

import json
import re
from typing import Any

VERDICTS = {
    "Supported",
    "Refuted",
    "Conflicting Evidence",
    "Not Enough Evidence",
}
KNOWLEDGE_BASES = {"direct_recall", "inference", "insufficient_knowledge"}
INTERNAL_FIELDS = {
    "verdict",
    "confidence",
    "knowledge_basis",
    "rationale",
    "decisive_propositions",
    "premise_concerns",
}
RAG_FIELDS = {"verdict", "confidence", "justification", "questions"}
RAG_QUESTION_FIELDS = {"question", "status", "answer", "selected_rank", "evidence"}
RAG_QUESTION_STATUSES = {"answered", "none", "dropped"}


class ContractError(ValueError):
    """Raised when an LLM response does not match its stage contract."""


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract one JSON object from plain or fenced model output."""

    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", candidate, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ContractError("Response is not a valid JSON object") from exc
    if not isinstance(value, dict):
        raise ContractError("Response must be a JSON object")
    return value


def _short_string_list(value: Any, field: str, *, maximum: int = 5) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ContractError(f"{field} must be a list with at most {maximum} entries")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ContractError(f"{field} entries must be non-empty strings")
        result.append(item.strip())
    return result


def parse_internal_judgment(text: str) -> dict[str, Any]:
    value = extract_json_object(text)
    fields = set(value)
    if fields != INTERNAL_FIELDS:
        missing = sorted(INTERNAL_FIELDS - fields)
        extra = sorted(fields - INTERNAL_FIELDS)
        raise ContractError(f"Internal judgment fields mismatch; missing={missing}, extra={extra}")
    if value["verdict"] not in VERDICTS:
        raise ContractError(f"Invalid verdict: {value['verdict']!r}")
    confidence = value["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ContractError("confidence must be numeric")
    confidence = float(confidence)
    if not 0 <= confidence <= 1:
        raise ContractError("confidence must be in [0, 1]")
    if value["knowledge_basis"] not in KNOWLEDGE_BASES:
        raise ContractError(f"Invalid knowledge_basis: {value['knowledge_basis']!r}")
    if not isinstance(value["rationale"], str) or not value["rationale"].strip():
        raise ContractError("rationale must be a non-empty string")
    return {
        "verdict": value["verdict"],
        "confidence": confidence,
        "knowledge_basis": value["knowledge_basis"],
        "rationale": value["rationale"].strip(),
        "decisive_propositions": _short_string_list(
            value["decisive_propositions"], "decisive_propositions"
        ),
        "premise_concerns": _short_string_list(value["premise_concerns"], "premise_concerns"),
    }


def validate_rag_judgment(value: Any) -> dict[str, Any]:
    """Validate a normalized RAG endpoint artifact produced by any upstream pipeline."""

    if not isinstance(value, dict) or set(value) != RAG_FIELDS:
        fields = set(value) if isinstance(value, dict) else set()
        raise ContractError(
            "RAG judgment fields mismatch; "
            f"missing={sorted(RAG_FIELDS - fields)}, extra={sorted(fields - RAG_FIELDS)}"
        )
    if value["verdict"] not in VERDICTS:
        raise ContractError(f"Invalid verdict: {value['verdict']!r}")
    confidence = value["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ContractError("confidence must be numeric")
    confidence = float(confidence)
    if not 0 <= confidence <= 1:
        raise ContractError("confidence must be in [0, 1]")
    justification = value["justification"]
    if not isinstance(justification, str) or not justification.strip():
        raise ContractError("justification must be a non-empty string")
    questions = value["questions"]
    if not isinstance(questions, list) or len(questions) > 30:
        raise ContractError("questions must be a list with at most 30 entries")

    normalized_questions: list[dict[str, Any]] = []
    for index, question in enumerate(questions):
        if not isinstance(question, dict) or set(question) != RAG_QUESTION_FIELDS:
            fields = set(question) if isinstance(question, dict) else set()
            raise ContractError(
                f"questions[{index}] fields mismatch; "
                f"missing={sorted(RAG_QUESTION_FIELDS - fields)}, "
                f"extra={sorted(fields - RAG_QUESTION_FIELDS)}"
            )
        question_text = question["question"]
        if not isinstance(question_text, str) or not question_text.strip():
            raise ContractError(f"questions[{index}].question must be a non-empty string")
        status = question["status"]
        if status not in RAG_QUESTION_STATUSES:
            raise ContractError(f"questions[{index}].status is invalid")
        answer = question["answer"]
        if answer is not None and (not isinstance(answer, str) or not answer.strip()):
            raise ContractError(f"questions[{index}].answer must be null or a non-empty string")
        if status == "answered" and answer is None:
            raise ContractError(f"questions[{index}].answer is required when status=answered")
        selected_rank = question["selected_rank"]
        if selected_rank is not None and (
            isinstance(selected_rank, bool)
            or not isinstance(selected_rank, int)
            or selected_rank < 1
        ):
            raise ContractError(f"questions[{index}].selected_rank must be null or >= 1")
        evidence = _short_string_list(
            question["evidence"], f"questions[{index}].evidence", maximum=20
        )
        normalized_questions.append(
            {
                "question": question_text.strip(),
                "status": status,
                "answer": answer.strip() if answer is not None else None,
                "selected_rank": selected_rank,
                "evidence": evidence,
            }
        )
    return {
        "verdict": value["verdict"],
        "confidence": confidence,
        "justification": justification.strip(),
        "questions": normalized_questions,
    }


def parse_rag_judgment(text: str) -> dict[str, Any]:
    return validate_rag_judgment(extract_json_object(text))
