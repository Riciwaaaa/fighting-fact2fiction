from __future__ import annotations

import pytest

from parametric_rag_defense.query_trace import audit_question_trace, safe_ratio


def example_trace() -> dict:
    return {
        "plan": {"questions": [{"question": "q0"}, {"question": "q1"}, {"question": "q2"}]},
        "retrievals": [
            [{"is_poison": False}, {"is_poison": True}],
            [{"is_poison": True}],
            [{"is_poison": False}],
        ],
        "answers": {
            "answers": [
                {"question_index": 0, "selected_rank": 2},
                {"question_index": 1, "selected_rank": None},
                {"question_index": 2, "selected_rank": 1},
            ]
        },
    }


def test_audit_distinguishes_exposure_from_selection() -> None:
    result = audit_question_trace(example_trace())
    assert result["poison_exposed_question_indices"] == [0, 1]
    assert result["poison_selected_question_indices"] == [0]
    assert result["clean_selected_question_indices"] == [2]
    assert result["poison_exposed_row"] is True
    assert result["poison_selected_row"] is True
    assert result["retrieved_poison_document_count"] == 2


def test_audit_rejects_bad_selected_rank() -> None:
    trace = example_trace()
    trace["answers"]["answers"][0]["selected_rank"] = 3
    with pytest.raises(ValueError, match="Invalid selected rank"):
        audit_question_trace(trace)


def test_safe_ratio() -> None:
    assert safe_ratio(3, 2) == 1.5
    assert safe_ratio(1, 0) is None
