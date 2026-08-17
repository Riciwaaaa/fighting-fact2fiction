import pytest

from parametric_rag_defense.contracts import ContractError
from parametric_rag_defense.rag_stress_arbiter import (
    build_stress_arbiter_packet,
    champion_prediction,
    parse_stress_arbiter,
)


def sample(verdict: str) -> dict:
    return {
        "verdict": verdict,
        "confidence": 0.8,
        "knowledge_basis": "direct_recall",
        "decisive_propositions": ["fact"],
        "premise_concerns": [],
        "rationale": "reason",
    }


def test_champion_prediction_reproduces_typed_rule() -> None:
    row = {
        "counter_loose_label": "Supported",
        "rag_prediction": "Supported",
        "memory_prediction": "Refuted",
        "cascade_prediction": "Refuted",
    }
    assert champion_prediction(row) == "Supported"
    row["counter_loose_label"] = "Not Enough Evidence"
    assert champion_prediction(row) == "Refuted"


def test_control_packet_withholds_stress_record() -> None:
    packet = build_stress_arbiter_packet(
        variant="control",
        claim="claim",
        claim_date="date",
        neutral_claim_plan={"central_proposition": "p"},
        rag_prediction="Supported",
        memory_prediction="Refuted",
        champion="Supported",
        internal_samples=[sample("Refuted")] * 3,
        original_rag_confidence=0.7,
        original_answered_count=4,
        original_question_count=10,
        stress_views=[],
    )
    assert packet["visible"]["stress_test_record"] == {
        "status": "withheld_matched_control",
        "views": [],
    }


def test_arbiter_contract_rejects_extra_fields() -> None:
    value = {
        "action": "keep_champion",
        "confidence": 0.5,
        "internal_reliability": "uncertain",
        "rag_stability": "split",
        "influence_concentration": "unclear",
        "decisive_signal": "mixed",
        "rationale": "mixed record",
        "gold": "Refuted",
    }
    with pytest.raises(ContractError):
        parse_stress_arbiter(value)
