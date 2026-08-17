"""Gold-free retrieval-drift alarms from sealed-memory/RAG disagreement."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import comb
from typing import Any


def disagreement_observation(row: Mapping[str, Any]) -> bool | None:
    """Return an alarm observation, excluding internally unanswerable claims."""

    if not bool(row["memory_answerable"]):
        return None
    return str(row["rag_prediction"]) != str(row["memory_prediction"])


def count_disagreements(rows: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
    observations = [
        value
        for row in rows
        if (value := disagreement_observation(row)) is not None
    ]
    return sum(observations), len(observations)


def beta_binomial_tail(
    disagreements: int,
    eligible: int,
    *,
    clean_disagreements: int,
    clean_eligible: int,
    alpha: float = 0.5,
    beta: float = 0.5,
) -> float:
    """Posterior-predictive upper tail under a clean beta-binomial model."""

    if eligible < 0 or not 0 <= disagreements <= eligible:
        raise ValueError("disagreement counts are invalid")
    if clean_eligible < 1 or not 0 <= clean_disagreements <= clean_eligible:
        raise ValueError("clean reference counts are invalid")
    if alpha <= 0 or beta <= 0:
        raise ValueError("beta prior parameters must be positive")

    posterior_alpha = clean_disagreements + alpha
    posterior_beta = clean_eligible - clean_disagreements + beta

    def rising(value: float, count: int) -> float:
        result = 1.0
        for index in range(count):
            result *= value + index
        return result

    denominator = rising(posterior_alpha + posterior_beta, eligible)
    total = 0.0
    for value in range(disagreements, eligible + 1):
        total += (
            comb(eligible, value)
            * rising(posterior_alpha, value)
            * rising(posterior_beta, eligible - value)
            / denominator
        )
    return min(1.0, max(0.0, total))


def drift_alarm(
    rows: Iterable[Mapping[str, Any]],
    *,
    clean_disagreements: int,
    clean_eligible: int,
    significance: float,
    minimum_eligible: int,
) -> dict[str, Any]:
    disagreements, eligible = count_disagreements(rows)
    tail = (
        beta_binomial_tail(
            disagreements,
            eligible,
            clean_disagreements=clean_disagreements,
            clean_eligible=clean_eligible,
        )
        if eligible
        else 1.0
    )
    return {
        "eligible": eligible,
        "disagreements": disagreements,
        "disagreement_rate": disagreements / eligible if eligible else None,
        "clean_eligible": clean_eligible,
        "clean_disagreements": clean_disagreements,
        "clean_disagreement_rate": clean_disagreements / clean_eligible,
        "posterior_predictive_upper_tail": tail,
        "alarm": eligible >= minimum_eligible and tail <= significance,
    }


def environment_prediction(row: Mapping[str, Any], *, alarm: bool) -> str:
    """Choose the corroboration blend normally and its memory-first fallback on alarm."""

    if alarm:
        return str(row["cascade_prediction"])
    return str(row["champion_prediction"])


def drift_level(
    posterior_predictive_upper_tail: float,
    *,
    warning_significance: float = 0.01,
    critical_significance: float = 0.0001,
) -> str:
    """Map a clean predictive tail probability to a predeclared evidence tier."""

    if not 0 < critical_significance <= warning_significance <= 1:
        raise ValueError("drift significance thresholds are invalid")
    if not 0 <= posterior_predictive_upper_tail <= 1:
        raise ValueError("posterior predictive tail must be in [0, 1]")
    if posterior_predictive_upper_tail <= critical_significance:
        return "critical"
    if posterior_predictive_upper_tail <= warning_significance:
        return "warning"
    return "normal"


def tiered_environment_prediction(row: Mapping[str, Any], *, level: str) -> str:
    """Tighten corroboration semantics as retrieval drift increases."""

    if level == "normal":
        return str(row["champion_prediction"])
    if level == "warning":
        return str(row["strict_champion_prediction"])
    if level == "critical":
        return str(row["cascade_prediction"])
    raise ValueError(f"Unknown drift level: {level}")
