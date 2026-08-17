"""Semantic guard for the neutral firewalled endpoint selector."""

from __future__ import annotations

from typing import Any, Mapping

from .neutral_firewall import endpoint_prediction


def strict_firewalled_selection(
    *,
    endpoint_labels: Mapping[str, Any],
    support_judgment: Mapping[str, Any],
    counter_judgment: Mapping[str, Any],
    selector_judgment: Mapping[str, Any],
) -> dict[str, Any]:
    """Enforce the selector prompt's predeclared necessary condition for retrieval.

    The LLM remains responsible for all analysis and endpoint selection. This guard only rejects a
    retrieval choice when the two retrieval-isolated judgments do not both converge on the
    retrieval endpoint's existing label with direct factual propositions. Rejected choices fall
    back to memory, exactly as stated in the frozen safety policy.
    """

    requested = selector_judgment.get("selected_endpoint")
    if requested not in {"retrieval", "memory"}:
        raise ValueError(f"Invalid requested endpoint: {requested!r}")
    retrieval_prediction = endpoint_prediction(endpoint_labels, "retrieval")
    support_verdict = support_judgment.get("verdict")
    counter_verdict = counter_judgment.get("verdict")
    direct_factual_support = (
        support_judgment.get("knowledge_basis") == "direct_recall"
        and counter_judgment.get("knowledge_basis") == "direct_recall"
        and bool(support_judgment.get("decisive_propositions"))
        and bool(counter_judgment.get("decisive_propositions"))
    )
    convergence = (
        retrieval_prediction is not None
        and support_verdict == retrieval_prediction
        and counter_verdict == retrieval_prediction
    )
    retrieval_admissible = convergence and direct_factual_support
    selected = "retrieval" if requested == "retrieval" and retrieval_admissible else "memory"
    return {
        "requested_endpoint": requested,
        "selected_endpoint": selected,
        "semantic_guard_applied": requested == "retrieval" and not retrieval_admissible,
        "retrieval_convergence": convergence,
        "direct_factual_support": direct_factual_support,
        "retrieval_admissible": retrieval_admissible,
        "prediction": endpoint_prediction(endpoint_labels, selected),
    }
