"""Contracts for retrieval-independent decomposition and rationale-firewalled selection."""

from __future__ import annotations

from typing import Any, Mapping

from .contracts import ContractError, extract_json_object

NEUTRAL_PLAN_CONTRACT_VERSION = "neutral-claim-plan-v1"
FIREWALLED_SELECTOR_CONTRACT_VERSION = "firewalled-endpoint-selector-v1"
NEUTRAL_PLAN_FIELDS = {
    "central_proposition",
    "support_probe",
    "refutation_probe",
    "temporal_scope",
    "ambiguities",
}


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    return value.strip()


def _text_list(value: Any, field: str, *, maximum: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ContractError(f"{field} must be a list with at most {maximum} items")
    return [_text(item, f"{field}[{index}]") for index, item in enumerate(value)]


def parse_neutral_plan(value: Any) -> dict[str, Any]:
    """Validate a claim-only plan that deliberately contains no verdict or confidence."""

    if not isinstance(value, Mapping):
        raise ContractError("Neutral plan response must be an object")
    if set(value) != NEUTRAL_PLAN_FIELDS:
        raise ContractError(
            "Neutral plan fields mismatch; "
            f"missing={sorted(NEUTRAL_PLAN_FIELDS-set(value))}, "
            f"extra={sorted(set(value)-NEUTRAL_PLAN_FIELDS)}"
        )
    return {
        "central_proposition": _text(value["central_proposition"], "central_proposition"),
        "support_probe": _text(value["support_probe"], "support_probe"),
        "refutation_probe": _text(value["refutation_probe"], "refutation_probe"),
        "temporal_scope": _text(value["temporal_scope"], "temporal_scope"),
        "ambiguities": _text_list(value["ambiguities"], "ambiguities", maximum=3),
    }


def parse_neutral_plan_text(text: str) -> dict[str, Any]:
    return parse_neutral_plan(extract_json_object(text))


def endpoint_prediction(endpoint_labels: Mapping[str, Any], endpoint: str) -> str | None:
    if endpoint not in {"retrieval", "memory"}:
        raise ValueError(f"Unknown endpoint: {endpoint}")
    value = endpoint_labels[endpoint]
    return value if isinstance(value, str) else None
