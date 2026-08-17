from parametric_rag_defense.rag_stress import (
    assertion_units,
    build_stress_views,
    complementary_unit_halves,
    dominant_aligned_cluster,
    parse_stress_answers,
    passage_document_map,
)
from parametric_rag_defense.contracts import ContractError


def test_passage_document_map_keeps_collapsed_documents_together() -> None:
    packet = {
        "passages": [{"passage_id": "p1", "text": "same"}],
        "retrieval_questions": [
            {"question": "q", "passage_ids": ["p1"]}
        ],
    }
    endpoint = {
        "questions": [
            {"evidence": ["[evidence_q1_r1] same", "[evidence_q1_r2] same"]}
        ]
    }
    trace = {"retrievals": [[{"document_id": "a"}, {"document_id": "b"}]]}
    assert passage_document_map(
        packet_visible=packet, endpoint_judgment=endpoint, trace=trace
    ) == {"p1": {"a", "b"}}


def test_assertion_units_add_unclustered_singletons() -> None:
    judgment = {
        "content_clusters": [
            {
                "cluster_id": "c1",
                "passage_ids": ["p1"],
                "stance": "supports",
                "directness": "direct",
                "shared_assertion": "x",
            }
        ]
    }
    units = assertion_units(
        evidence_judgment=judgment,
        alias_documents={"p1": {"a"}, "p2": {"b"}},
    )
    assert [unit["unit_id"] for unit in units] == ["c1", "unclustered::p2"]


def test_halves_are_disjoint_complete_and_deterministic() -> None:
    units = [
        {"unit_id": "a", "document_ids": ["1", "2"]},
        {"unit_id": "b", "document_ids": ["3"]},
        {"unit_id": "c", "document_ids": ["4"]},
    ]
    first = complementary_unit_halves(units, task_key="task")
    second = complementary_unit_halves(list(reversed(units)), task_key="task")
    assert first == second
    assert first is not None
    assert set(first[0]).isdisjoint(first[1])
    assert set(first[0]) | set(first[1]) == {"a", "b", "c"}


def test_dominant_cluster_requires_direct_alignment() -> None:
    units = [
        {
            "unit_id": "small",
            "kind": "content_cluster",
            "stance": "supports",
            "directness": "direct",
            "document_ids": ["a"],
        },
        {
            "unit_id": "large",
            "kind": "content_cluster",
            "stance": "supports",
            "directness": "direct",
            "document_ids": ["b", "c"],
        },
        {
            "unit_id": "wrong",
            "kind": "content_cluster",
            "stance": "refutes",
            "directness": "direct",
            "document_ids": ["d", "e", "f"],
        },
    ]
    assert dominant_aligned_cluster(units, rag_prediction="Supported") == "large"
    assert dominant_aligned_cluster(units, rag_prediction="Not Enough Evidence") is None


def test_stress_views_never_retrieve_or_backfill() -> None:
    units = [
        {
            "unit_id": "c1",
            "kind": "content_cluster",
            "stance": "supports",
            "directness": "direct",
            "document_ids": ["a"],
        },
        {
            "unit_id": "c2",
            "kind": "content_cluster",
            "stance": "context",
            "directness": "none",
            "document_ids": ["b"],
        },
    ]
    retrievals = [[{"document_id": "a"}, {"document_id": "b"}], []]
    views = build_stress_views(
        task_key="task",
        rag_prediction="Supported",
        units=units,
        retrievals=retrievals,
    )
    assert {view["view_type"] for view in views} == {
        "half_a",
        "half_b",
        "dominant_aligned_cluster_removed",
    }
    for view in views:
        retained = {
            item["document_id"] for group in view["retrievals"] for item in group
        }
        assert retained == set(view["retained_document_ids"])
        assert retained <= {"a", "b"}


def test_stress_answer_adapter_discards_only_orphan_none_rank() -> None:
    def parser(text: str, result_counts: list[int]) -> dict:
        import json

        value = json.loads(text)
        item = value["answers"][0]
        if item["status"] == "none" and item["selected_rank"] is not None:
            raise ContractError("none answers require null answer and rank")
        return value

    text = (
        '{"answers":[{"question_index":0,"status":"none",'
        '"answer":null,"selected_rank":1}]}'
    )
    parsed = parse_stress_answers(text, result_counts=[1], base_parser=parser)
    assert parsed["answers"][0]["selected_rank"] is None


def test_stress_answer_adapter_does_not_repair_factual_content() -> None:
    def parser(text: str, result_counts: list[int]) -> dict:
        raise ContractError("invalid")

    text = (
        '{"answers":[{"question_index":0,"status":"none",'
        '"answer":"invented","selected_rank":1}]}'
    )
    try:
        parse_stress_answers(text, result_counts=[1], base_parser=parser)
    except ContractError:
        pass
    else:
        raise AssertionError("Adapter repaired more than an orphan rank")
