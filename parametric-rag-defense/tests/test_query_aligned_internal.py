from __future__ import annotations

import pytest

from parametric_rag_defense.contracts import ContractError
from parametric_rag_defense.query_aligned_internal import (
    eligible_conflict_indices,
    filter_suspect_documents,
    localized_conflict_gate,
    parse_internal_question_answers,
    parse_question_conflict_map,
    replay_case_key,
    suspect_document_ids,
)


def test_parse_internal_question_answers() -> None:
    value = parse_internal_question_answers(
        '{"answers":['
        '{"question_index":0,"status":"known","answer":"Yes.","confidence":0.8},'
        '{"question_index":1,"status":"unknown","answer":null,"confidence":0.2}'
        "]}",
        expected_questions=2,
    )
    assert value["answers"][0]["answer"] == "Yes."
    assert value["answers"][1]["answer"] is None


def test_parse_rejects_unknown_with_answer() -> None:
    with pytest.raises(ContractError, match="must use null"):
        parse_internal_question_answers(
            '{"answers":[{"question_index":0,"status":"unknown",'
            '"answer":"Maybe","confidence":0.2}]}',
            expected_questions=1,
        )


def test_case_key_covers_question_order() -> None:
    first = replay_case_key(
        model_id="m", claim_id=1, claim_date="date", questions=["a", "b"]
    )
    second = replay_case_key(
        model_id="m", claim_id=1, claim_date="date", questions=["b", "a"]
    )
    assert first != second


def test_parse_question_conflict_map() -> None:
    value = parse_question_conflict_map(
        '{"comparisons":['
        '{"question_index":0,"internal_state":"stable","relation":"contradicts",'
        '"note":"The answers give different dates."},'
        '{"question_index":1,"internal_state":"unknown","relation":"unclear",'
        '"note":"Both internal attempts are unknown."}'
        "]}",
        expected_questions=2,
    )
    assert value["comparisons"][0]["relation"] == "contradicts"


def test_conflict_fails_closed_without_stable_internal_answer() -> None:
    value = parse_question_conflict_map(
        '{"comparisons":[{"question_index":0,"internal_state":"unstable",'
        '"relation":"contradicts","note":"Different."},[]]}',
        expected_questions=1,
    )
    assert value["comparisons"][0]["relation"] == "unclear"


def test_eligible_conflicts_require_selected_evidence() -> None:
    conflict = {
        "comparisons": [
            {"question_index": 0, "internal_state": "stable", "relation": "contradicts"},
            {"question_index": 1, "internal_state": "stable", "relation": "contradicts"},
            {"question_index": 2, "internal_state": "unstable", "relation": "unclear"},
        ]
    }
    trace = {
        "answers": {
            "answers": [
                {"question_index": 0, "selected_rank": 2},
                {"question_index": 1, "selected_rank": None},
                {"question_index": 2, "selected_rank": 1},
            ]
        },
        "retrievals": [
            [{"document_id": "a"}, {"document_id": "b"}],
            [{"document_id": "c"}],
            [{"document_id": "d"}],
        ],
    }
    assert eligible_conflict_indices(conflict, trace) == [0]
    assert suspect_document_ids(conflict, trace) == {"b"}


def test_filter_suspect_documents_is_global_and_does_not_backfill() -> None:
    retrievals = [
        [{"document_id": "a"}, {"document_id": "b"}],
        [{"document_id": "b"}, {"document_id": "c"}],
    ]
    assert filter_suspect_documents(retrievals, {"b"}) == [
        [{"document_id": "a"}],
        [{"document_id": "c"}],
    ]
    assert len(retrievals[0]) == 2


def test_localized_conflict_gate() -> None:
    assert not localized_conflict_gate(stable_questions=0, conflict_questions=0)
    assert localized_conflict_gate(stable_questions=10, conflict_questions=2)
    assert localized_conflict_gate(stable_questions=9, conflict_questions=3)
    assert not localized_conflict_gate(stable_questions=10, conflict_questions=1)
    assert not localized_conflict_gate(stable_questions=10, conflict_questions=4)
