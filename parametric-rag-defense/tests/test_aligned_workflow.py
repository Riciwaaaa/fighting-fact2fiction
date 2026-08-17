from __future__ import annotations

import unittest

from parametric_rag_defense.aligned_workflow import (
    build_aligned_packet,
    parse_aligned_final,
    parse_aligned_router,
)
from parametric_rag_defense.contracts import ContractError


def internal(verdict: str) -> dict:
    return {
        "agreement_fraction": 1.0,
        "candidate_id": "candidate_A",
        "knowledge_basis_distribution": {"direct_recall": 3},
        "leading_verdicts": [verdict],
        "mean_confidence": 0.9,
        "repeat_count": 3,
        "samples": [],
        "verdict_distribution": {verdict: 3},
    }


def source_packet() -> dict:
    return {
        "packet_key": "p" * 64,
        "visible": {
            "claim": "A claim.",
            "claim_date": "2020-01-01",
            "retrieval_assessment": {},
            "memory_only_assessments": [internal("Refuted"), {**internal("Supported"), "candidate_id": "candidate_B"}],
        },
        "provenance": {
            "rag_task_key": "r" * 64,
            "internal_candidate_map": {"candidate_A": "model-a", "candidate_B": "model-b"},
            "internal_cache_keys": {"model-a": ["1", "2", "3"], "model-b": ["4", "5", "6"]},
        },
    }


def rag() -> dict:
    return {
        "verdict": "Supported",
        "confidence": 0.7,
        "justification": "The retrieved record supports the claim.",
        "questions": [
            {
                "question": "Did it happen?",
                "status": "answered",
                "answer": "Yes.",
                "selected_rank": 1,
                "evidence": ["First excerpt.", "Second excerpt."],
            }
        ],
    }


class AlignedWorkflowTests(unittest.TestCase):
    def test_packet_contains_only_same_model_candidate(self):
        packet = build_aligned_packet(
            source_packet=source_packet(), rag_judgment=rag(), model_id="model-a", variant="endpoint_only"
        )
        self.assertNotIn("candidate_id", packet["visible"]["memory_only_assessment"])
        self.assertEqual(packet["visible"]["memory_only_assessment"]["leading_verdicts"], ["Refuted"])
        self.assertNotIn("questions", packet["visible"]["retrieval_assessment"])

    def test_evidence_variant_keeps_all_normalized_excerpts(self):
        packet = build_aligned_packet(
            source_packet=source_packet(), rag_judgment=rag(), model_id="model-a", variant="evidence_aware"
        )
        excerpts = packet["visible"]["retrieval_assessment"]["questions"][0]["retrieved_excerpts"]
        self.assertEqual(excerpts, ["First excerpt.", "Second excerpt."])

    def test_router_and_final_contracts(self):
        router = {
            "route": "verify_proposition",
            "provisional_endpoint": "memory",
            "confidence": 0.7,
            "decisive_conflict": "The endpoints disagree about the event.",
            "pivotal_proposition": "The event occurred.",
            "assessment": "The remembered fact is stronger but should be checked.",
        }
        self.assertEqual(parse_aligned_router(router), router)
        final = {
            "selected_endpoint": "retrieval",
            "confidence": 0.8,
            "decisive_conflict": "The event occurrence is decisive.",
            "proposition_check_assessment": "The check supports occurrence.",
            "rationale": "The retrieval endpoint is better supported.",
        }
        self.assertEqual(parse_aligned_final(final), final)
        with self.assertRaises(ContractError):
            parse_aligned_router({**router, "route": "synthesize"})

    def test_router_repairs_one_unambiguous_field_typo(self):
        router = {
            "route": "verify_proposition",
            "provisional_endpoint": "memory",
            "confidence": 0.7,
            "decicisive_conflict": "The endpoints disagree about the event.",
            "pivotal_proposition": "The event occurred.",
            "assessment": "The remembered fact is stronger but should be checked.",
        }
        parsed = parse_aligned_router(router)
        self.assertEqual(parsed["decisive_conflict"], router["decicisive_conflict"])
        self.assertNotIn("decicisive_conflict", parsed)

    def test_router_rejects_nonlocal_field_substitution(self):
        router = {
            "route": "verify_proposition",
            "provisional_endpoint": "memory",
            "confidence": 0.7,
            "unrelated_field": "The endpoints disagree about the event.",
            "pivotal_proposition": "The event occurred.",
            "assessment": "The remembered fact is stronger but should be checked.",
        }
        with self.assertRaises(ContractError):
            parse_aligned_router(router)


if __name__ == "__main__":
    unittest.main()
