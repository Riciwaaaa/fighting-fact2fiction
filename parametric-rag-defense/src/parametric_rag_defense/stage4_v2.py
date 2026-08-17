"""Contracts and helpers for reviewer-controlled Stage 4 v2 workflows."""

from __future__ import annotations

from typing import Any, Mapping

from .contracts import ContractError, VERDICTS, extract_json_object

ARCHITECT_CONTRACT_VERSION = "stage4-architect-v2"
ADJUDICATOR_CONTRACT_VERSION = "stage4-adjudicator-v2"

ARCHITECT_FIELDS = {"disagreement_summary", "propositions", "planning_rationale"}
PROPOSITION_FIELDS = {
    "id",
    "role",
    "text",
    "effect_if_supported",
    "effect_if_refuted",
    "faithfulness_check",
}
ADJUDICATOR_FIELDS = {
    "action",
    "verdict",
    "confidence",
    "anchor_assessment",
    "proposition_assessment",
    "endpoint_assessment",
    "rationale",
}
PROPOSITION_ROLES = {"claim_core", "discriminator"}
CLAIM_EFFECTS = {"supports_claim", "refutes_claim", "undetermined"}
ACTIONS = {"select_retrieval", "select_memory", "select_internal"}


def _exact_fields(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    observed = set(value)
    if observed != expected:
        raise ContractError(
            f"{name} fields mismatch; missing={sorted(expected-observed)}, "
            f"extra={sorted(observed-expected)}"
        )


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")
    return value.strip()


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError("confidence must be numeric")
    result = float(value)
    if not 0 <= result <= 1:
        raise ContractError("confidence must be in [0, 1]")
    return result


def parse_architect(value: Any) -> dict[str, Any]:
    """Validate the two-proposition plan used by Stage 4 v2."""

    if not isinstance(value, dict):
        raise ContractError("Architect response must be an object")
    _exact_fields(value, ARCHITECT_FIELDS, "Architect")
    raw_propositions = value["propositions"]
    if not isinstance(raw_propositions, list) or len(raw_propositions) != 2:
        raise ContractError("propositions must contain exactly two entries")
    propositions = []
    roles = set()
    identifiers = set()
    for index, proposition in enumerate(raw_propositions):
        if not isinstance(proposition, dict):
            raise ContractError(f"propositions[{index}] must be an object")
        _exact_fields(proposition, PROPOSITION_FIELDS, f"propositions[{index}]")
        identifier = _text(proposition["id"], f"propositions[{index}].id")
        role = proposition["role"]
        if role not in PROPOSITION_ROLES:
            raise ContractError(f"Invalid proposition role: {role!r}")
        if proposition["effect_if_supported"] not in CLAIM_EFFECTS:
            raise ContractError("Invalid effect_if_supported")
        if proposition["effect_if_refuted"] not in CLAIM_EFFECTS:
            raise ContractError("Invalid effect_if_refuted")
        propositions.append(
            {
                "id": identifier,
                "role": role,
                "text": _text(proposition["text"], f"propositions[{index}].text"),
                "effect_if_supported": proposition["effect_if_supported"],
                "effect_if_refuted": proposition["effect_if_refuted"],
                "faithfulness_check": _text(
                    proposition["faithfulness_check"],
                    f"propositions[{index}].faithfulness_check",
                ),
            }
        )
        roles.add(role)
        identifiers.add(identifier)
    if roles != PROPOSITION_ROLES:
        raise ContractError("propositions must include claim_core and discriminator exactly once")
    if len(identifiers) != 2:
        raise ContractError("proposition IDs must be unique")
    return {
        "disagreement_summary": _text(value["disagreement_summary"], "disagreement_summary"),
        "propositions": propositions,
        "planning_rationale": _text(value["planning_rationale"], "planning_rationale"),
    }


def parse_architect_text(text: str) -> dict[str, Any]:
    return parse_architect(extract_json_object(text))


def parse_adjudicator(value: Any) -> dict[str, Any]:
    """Validate a selector-or-revision decision."""

    if not isinstance(value, dict):
        raise ContractError("Adjudicator response must be an object")
    _exact_fields(value, ADJUDICATOR_FIELDS, "Adjudicator")
    if value["action"] not in ACTIONS:
        raise ContractError(f"Invalid action: {value['action']!r}")
    if value["verdict"] not in VERDICTS:
        raise ContractError(f"Invalid verdict: {value['verdict']!r}")
    return {
        "action": value["action"],
        "verdict": value["verdict"],
        "confidence": _confidence(value["confidence"]),
        "anchor_assessment": _text(value["anchor_assessment"], "anchor_assessment"),
        "proposition_assessment": _text(
            value["proposition_assessment"], "proposition_assessment"
        ),
        "endpoint_assessment": _text(value["endpoint_assessment"], "endpoint_assessment"),
        "rationale": _text(value["rationale"], "rationale"),
    }


def parse_adjudicator_text(text: str) -> dict[str, Any]:
    return parse_adjudicator(extract_json_object(text))


def validate_action_verdict(
    judgment: Mapping[str, Any],
    *,
    retrieval_verdict: str,
    memory_verdict: str,
    internal_verdict: str | None = None,
) -> None:
    """Require endpoint-selection actions to copy the corresponding endpoint verdict."""

    expected = {
        "select_retrieval": retrieval_verdict,
        "select_memory": memory_verdict,
        "select_internal": internal_verdict,
    }.get(judgment["action"])
    if expected is not None and judgment["verdict"] != expected:
        raise ContractError(
            f"{judgment['action']} must copy {expected!r}, observed {judgment['verdict']!r}"
        )
