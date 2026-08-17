from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from parametric_rag_defense.stage2_packets import (
    Stage2PacketError,
    build_packet,
    candidate_aliases,
    store_immutable,
    validate_visible_packet,
)


def internal(verdict: str = "Refuted") -> dict:
    return {
        "verdict": verdict,
        "confidence": 0.8,
        "knowledge_basis": "direct_recall",
        "rationale": "I recall the decisive fact.",
        "decisive_propositions": ["The event did not occur."],
        "premise_concerns": [],
    }


def rag() -> dict:
    return {
        "verdict": "Supported",
        "confidence": 0.7,
        "justification": "The retrieved text says the event occurred.",
        "questions": [
            {
                "question": "Did it occur?",
                "status": "answered",
                "answer": "Yes.",
                "selected_rank": 2,
                "evidence": ["First excerpt.", "Second excerpt."],
            }
        ],
    }


class Stage2PacketTests(unittest.TestCase):
    def test_rejects_inference_metadata_and_origin_markers(self):
        with self.assertRaises(Stage2PacketError):
            validate_visible_packet({"attack_condition": "hidden"})
        with self.assertRaises(Stage2PacketError):
            validate_visible_packet({"evidence": "[poison:2] text"})
        with self.assertRaises(Stage2PacketError):
            validate_visible_packet({"evidence": "https://example.test"})

    def test_builds_masked_immutable_packet(self):
        samples = {
            "model-a": [internal(), internal(), internal("Supported")],
            "model-b": [internal(), internal(), internal()],
        }
        keys = {"model-a": ["a", "b", "c"], "model-b": ["d", "e", "f"]}
        packet = build_packet(
            claim_id=7,
            claim="A claim",
            claim_date="2020-01-01",
            rag_task_key="r" * 64,
            rag_judgment=rag(),
            internal_samples=samples,
            internal_cache_keys=keys,
        )
        self.assertNotIn("model-a", str(packet["visible"]))
        first = packet["visible"]["retrieval_assessment"]["questions"][0]
        self.assertEqual(first["selected_evidence"], ["Second excerpt."])
        with tempfile.TemporaryDirectory() as directory:
            path, cached = store_immutable(Path(directory), packet)
            same_path, same_cached = store_immutable(Path(directory), packet)
            self.assertTrue(path.exists())
            self.assertFalse(cached)
            self.assertTrue(same_cached)
            self.assertEqual(path, same_path)

    def test_aliases_are_stable_and_permuted_by_claim(self):
        model_ids = ["model-a", "model-b", "model-c"]
        self.assertEqual(candidate_aliases(7, model_ids), candidate_aliases(7, model_ids))
        self.assertEqual(set(candidate_aliases(7, model_ids).values()), {
            "candidate_A", "candidate_B", "candidate_C"
        })


if __name__ == "__main__":
    unittest.main()
