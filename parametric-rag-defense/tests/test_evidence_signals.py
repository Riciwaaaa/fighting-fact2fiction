from __future__ import annotations

import unittest

from parametric_rag_defense.contracts import ContractError
from parametric_rag_defense.evidence_signals import (
    build_evidence_packet,
    parse_evidence_map,
)


def rag() -> dict:
    return {
        "verdict": "Supported",
        "confidence": 0.7,
        "justification": "The retrieved record supports the claim.",
        "questions": [
            {
                "question": "Did the event happen?",
                "status": "answered",
                "answer": "Yes.",
                "selected_rank": 1,
                "evidence": [
                    "[evidence_q1_r1] Repeated passage.",
                    "[evidence_q1_r2] Distinct passage.",
                ],
            },
            {
                "question": "When did it happen?",
                "status": "none",
                "answer": None,
                "selected_rank": None,
                "evidence": ["[evidence_q2_r1] Repeated passage."],
            },
        ],
    }


def plan() -> dict:
    return {
        "central_proposition": "The event happened.",
        "support_probe": "A record documents the event.",
        "refutation_probe": "A record establishes that it did not happen.",
        "temporal_scope": "The stated period.",
        "ambiguities": [],
    }


def evidence_map(passage_ids: list[str]) -> dict:
    return {
        "passage_assessments": [
            {
                "passage_id": passage_id,
                "stance": "supports",
                "directness": "direct",
                "key_assertion": "The event happened.",
                "quality_concern": "none",
            }
            for passage_id in passage_ids
        ],
        "content_clusters": [
            {
                "cluster_id": f"cluster_{index:02d}",
                "passage_ids": [passage_id],
                "shared_assertion": "The event happened.",
                "stance": "supports",
                "directness": "direct",
            }
            for index, passage_id in enumerate(passage_ids, 1)
        ],
        "overall_assessment": {
            "direction": "supports",
            "direct_support_cluster_ids": ["cluster_01"],
            "direct_refutation_cluster_ids": [],
            "evidence_conflict": False,
            "summary": "The passages support the proposition.",
        },
    }


class EvidenceSignalTests(unittest.TestCase):
    def test_packet_exactly_deduplicates_and_hides_endpoint(self):
        packet = build_evidence_packet(
            claim="The event happened.",
            claim_date="2020-01-01",
            rag_task_key="a" * 64,
            rag_judgment=rag(),
            neutral_plan=plan(),
            neutral_plan_cache_key="b" * 64,
            same_model_id="model-a",
        )
        visible = packet["visible"]
        self.assertEqual(len(visible["passages"]), 2)
        serialized = str(visible)
        self.assertNotIn("Supported", serialized)
        self.assertNotIn("confidence", serialized)
        repeated_alias = next(
            item["passage_id"]
            for item in visible["passages"]
            if item["text"] == "Repeated passage."
        )
        self.assertIn(repeated_alias, visible["retrieval_questions"][0]["passage_ids"])
        self.assertIn(repeated_alias, visible["retrieval_questions"][1]["passage_ids"])

    def test_packet_drops_non_content_visual_separators(self):
        judgment = rag()
        judgment["questions"][0]["evidence"].append(
            "[evidence_q1_r3] ______________________________"
        )
        packet = build_evidence_packet(
            claim="The event happened.",
            claim_date="2020-01-01",
            rag_task_key="a" * 64,
            rag_judgment=judgment,
            neutral_plan=plan(),
            neutral_plan_cache_key="b" * 64,
            same_model_id="model-a",
        )
        self.assertEqual(len(packet["visible"]["passages"]), 2)
        self.assertNotIn(
            "______________________________",
            [item["text"] for item in packet["visible"]["passages"]],
        )

    def test_packet_rejects_when_every_passage_is_non_content(self):
        judgment = rag()
        for question in judgment["questions"]:
            question["evidence"] = ["[evidence_q1_r1] ______"]
        with self.assertRaisesRegex(ValueError, "at least one retrieved passage"):
            build_evidence_packet(
                claim="The event happened.",
                claim_date="2020-01-01",
                rag_task_key="a" * 64,
                rag_judgment=judgment,
                neutral_plan=plan(),
                neutral_plan_cache_key="b" * 64,
                same_model_id="model-a",
            )

    def test_map_requires_complete_passage_partition(self):
        value = evidence_map(["passage_01", "passage_02"])
        parsed = parse_evidence_map(
            value, expected_passage_ids={"passage_01", "passage_02"}
        )
        self.assertEqual(parsed["overall_assessment"]["direction"], "supports")
        value["content_clusters"][1]["passage_ids"] = ["passage_01"]
        with self.assertRaises(ContractError):
            parse_evidence_map(
                value, expected_passage_ids={"passage_01", "passage_02"}
            )

    def test_map_allows_assessed_context_outside_content_clusters(self):
        value = evidence_map(["passage_01", "passage_02"])
        value["content_clusters"] = value["content_clusters"][:1]
        parsed = parse_evidence_map(
            value, expected_passage_ids={"passage_01", "passage_02"}
        )
        self.assertEqual(len(parsed["passage_assessments"]), 2)
        self.assertEqual(len(parsed["content_clusters"]), 1)

    def test_map_rejects_missing_passage_assessment(self):
        value = evidence_map(["passage_01"])
        with self.assertRaisesRegex(ContractError, "coverage mismatch"):
            parse_evidence_map(
                value, expected_passage_ids={"passage_01", "passage_02"}
            )


if __name__ == "__main__":
    unittest.main()
