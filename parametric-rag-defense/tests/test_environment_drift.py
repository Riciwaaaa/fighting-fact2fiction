from parametric_rag_defense.environment_drift import (
    beta_binomial_tail,
    count_disagreements,
    drift_level,
    drift_alarm,
    environment_prediction,
    tiered_environment_prediction,
)


def row(*, answerable: bool, rag: str, memory: str) -> dict:
    return {
        "memory_answerable": answerable,
        "rag_prediction": rag,
        "memory_prediction": memory,
        "cascade_prediction": memory if answerable else rag,
        "champion_prediction": rag,
        "strict_champion_prediction": memory,
    }


def test_unanswerable_memory_is_not_an_alarm_observation() -> None:
    rows = [
        row(answerable=True, rag="Supported", memory="Refuted"),
        row(answerable=False, rag="Supported", memory="Not Enough Evidence"),
    ]
    assert count_disagreements(rows) == (1, 1)


def test_beta_binomial_tail_decreases_with_more_disagreement() -> None:
    low = beta_binomial_tail(
        3, 20, clean_disagreements=10, clean_eligible=100
    )
    high = beta_binomial_tail(
        12, 20, clean_disagreements=10, clean_eligible=100
    )
    assert 0 <= high < low <= 1


def test_alarm_requires_minimum_batch_and_tail_threshold() -> None:
    observations = [
        row(answerable=True, rag="Supported", memory="Refuted") for _ in range(20)
    ]
    assert not drift_alarm(
        observations[:9],
        clean_disagreements=5,
        clean_eligible=100,
        significance=0.01,
        minimum_eligible=10,
    )["alarm"]
    assert drift_alarm(
        observations,
        clean_disagreements=5,
        clean_eligible=100,
        significance=0.01,
        minimum_eligible=10,
    )["alarm"]


def test_alarm_reverts_champion_to_answerability_fallback() -> None:
    answerable = row(answerable=True, rag="Supported", memory="Refuted")
    unanswerable = row(
        answerable=False, rag="Supported", memory="Not Enough Evidence"
    )
    assert environment_prediction(answerable, alarm=True) == "Refuted"
    assert environment_prediction(unanswerable, alarm=True) == "Supported"
    assert environment_prediction(answerable, alarm=False) == "Supported"


def test_tiered_policy_tightens_corroboration() -> None:
    value = row(answerable=True, rag="Supported", memory="Refuted")
    assert drift_level(0.1) == "normal"
    assert drift_level(0.005) == "warning"
    assert drift_level(0.00001) == "critical"
    assert tiered_environment_prediction(value, level="normal") == "Supported"
    assert tiered_environment_prediction(value, level="warning") == "Refuted"
    assert tiered_environment_prediction(value, level="critical") == "Refuted"
