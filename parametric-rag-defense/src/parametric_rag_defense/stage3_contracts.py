"""Strict contracts for Stage 3 evidence criticism and claim-level arbitration."""

from __future__ import annotations

import re
from typing import Any

from .contracts import ContractError, VERDICTS, extract_json_object

STAGE3_CONTRACT_VERSION = "v2-qwen-rationate-field-alias"
CRITIC_FIELDS = {
    "evidence_direction",
    "coverage",
    "coherence",
    "claim_premise_risk",
    "summary",
    "decisive_evidence",
    "unresolved_points",
}
ARBITER_FIELDS = {
    "route",
    "final_verdict",
    "confidence",
    "decisive_conflict",
    "epistemic_assessment",
    "reason_codes",
    "pivotal_propositions",
    "rationale",
}
REASON_CODES = {
    "endpoints_agree",
    "retrieval_well_supported",
    "retrieval_internally_inconsistent",
    "retrieval_poor_coverage",
    "memory_consensus",
    "memory_direct_recall",
    "memory_inference_only",
    "memory_insufficient",
    "memory_disagreement",
    "premise_conflict",
    "unresolved_decisive_conflict",
}
_URL = re.compile(r"https?://", re.IGNORECASE)
_ORIGIN_ID = re.compile(r"\b(?:clean|poison):\d+\b", re.IGNORECASE)


def _exact_fields(value: dict[str, Any], required: set[str], name: str) -> None:
    if set(value) != required:
        raise ContractError(
            f"{name} fields mismatch; missing={sorted(required-set(value))}, "
            f"extra={sorted(set(value)-required)}"
        )


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    result = value.strip()
    if _URL.search(result) or _ORIGIN_ID.search(result):
        raise ContractError(f"{field} contains forbidden source metadata")
    return result


def _strings(value: Any, field: str, maximum: int, *, minimum: int = 0) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ContractError(f"{field} must contain between {minimum} and {maximum} strings")
    result = [_text(item, f"{field}[]") for item in value]
    if len(set(result)) != len(result):
        raise ContractError(f"{field} must not contain duplicates")
    return result


def parse_evidence_critic(text: str) -> dict[str, Any]:
    value = extract_json_object(text)
    _exact_fields(value, CRITIC_FIELDS, "Evidence critic")
    allowed = {
        "evidence_direction": {"supports_claim", "refutes_claim", "mixed", "insufficient"},
        "coverage": {"strong", "partial", "weak"},
        "coherence": {"consistent", "conflicted"},
        "claim_premise_risk": {"low", "medium", "high"},
    }
    for field, choices in allowed.items():
        if value[field] not in choices:
            raise ContractError(f"Invalid {field}: {value[field]!r}")
    return {
        "evidence_direction": value["evidence_direction"],
        "coverage": value["coverage"],
        "coherence": value["coherence"],
        "claim_premise_risk": value["claim_premise_risk"],
        "summary": _text(value["summary"], "summary"),
        "decisive_evidence": _strings(value["decisive_evidence"], "decisive_evidence", 3),
        "unresolved_points": _strings(value["unresolved_points"], "unresolved_points", 3),
    }


def parse_claim_arbiter(text: str) -> dict[str, Any]:
    value = extract_json_object(text)
    # Qwen 3.5 deterministically emits this single field-name typo on a small prompt subset, even
    # across format retries.  The mapping is unambiguous and changes no response content.
    if "rationate" in value and "rationale" not in value:
        value = {"rationale" if key == "rationate" else key: child for key, child in value.items()}
    _exact_fields(value, ARBITER_FIELDS, "Claim arbiter")
    if value["route"] not in {"trust_retrieval", "trust_memory", "synthesize", "escalate"}:
        raise ContractError(f"Invalid route: {value['route']!r}")
    if value["final_verdict"] not in VERDICTS:
        raise ContractError(f"Invalid final_verdict: {value['final_verdict']!r}")
    confidence = value["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ContractError("confidence must be numeric")
    confidence = float(confidence)
    if not 0 <= confidence <= 1:
        raise ContractError("confidence must be in [0, 1]")
    reason_codes = _strings(value["reason_codes"], "reason_codes", 5, minimum=1)
    unknown_codes = set(reason_codes) - REASON_CODES
    if unknown_codes:
        raise ContractError(f"Unknown reason codes: {sorted(unknown_codes)}")
    return {
        "route": value["route"],
        "final_verdict": value["final_verdict"],
        "confidence": confidence,
        "decisive_conflict": _text(value["decisive_conflict"], "decisive_conflict"),
        "epistemic_assessment": _text(value["epistemic_assessment"], "epistemic_assessment"),
        "reason_codes": reason_codes,
        "pivotal_propositions": _strings(
            value["pivotal_propositions"], "pivotal_propositions", 3
        ),
        "rationale": _text(value["rationale"], "rationale"),
    }
