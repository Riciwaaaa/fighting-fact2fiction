from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from parametric_rag_defense.rag_artifacts import (
    RAGArtifactError,
    normalize_record,
    store_immutable,
)


def task(clean: bool = False):
    condition = {
        "id": "clean" if clean else "poisonedrag_n5",
        "attack_family": "none" if clean else "poisonedrag",
        "strength": 0 if clean else 5,
        "strength_unit": "none" if clean else "malicious_documents_per_target",
    }
    return {
        "task_schema_version": 1,
        "task_type": "rag_endpoint",
        "tier": "development_sweep",
        "split": "development",
        "claim_id": 7,
        "model_id": "model-a",
        "provider": "provider-a",
        "model": "model-a-v1",
        "condition": condition,
        "attack_seed": None if clean else 101,
        "task_key": "a" * 64,
    }


def record(clean: bool = False):
    clean_count = 100
    injected = 0 if clean else 5
    return {
        "task_key": "a" * 64,
        "judgment": {
            "verdict": "Refuted",
            "confidence": 0.8,
            "justification": "The adopted answers refute the central proposition.",
            "questions": [
                {
                    "question": "Did the event occur?",
                    "status": "answered",
                    "answer": "No.",
                    "selected_rank": 1,
                    "evidence": ["A normalized excerpt without its URL."],
                }
            ],
        },
        "audit": {
            "clean_documents_before_injection": clean_count,
            "poison_documents_injected": injected,
            "realized_poison_fraction": injected / (clean_count + injected),
            "retrieved_documents_total": 5,
            "retrieved_poison_documents": 0 if clean else 2,
        },
        "provenance": {"upstream": "test-adapter", "upstream_commit": "abc123"},
    }


class RAGArtifactTests(unittest.TestCase):
    def test_normalize_and_immutable_reuse(self):
        artifact = normalize_record(record(), task())
        with tempfile.TemporaryDirectory() as directory:
            first_path, first_cached = store_immutable(Path(directory), artifact)
            second_path, second_cached = store_immutable(Path(directory), artifact)
            self.assertEqual(first_path, second_path)
            self.assertFalse(first_cached)
            self.assertTrue(second_cached)

    def test_reject_gold_and_mask_raw_url(self):
        with_gold = record()
        with_gold["provenance"]["gold_label"] = "Refuted"
        with self.assertRaises(RAGArtifactError):
            normalize_record(with_gold, task())
        with_url = record()
        with_url["judgment"]["questions"][0]["evidence"] = ["https://example.test/doc"]
        artifact = normalize_record(with_url, task())
        self.assertEqual(
            artifact["judgment"]["questions"][0]["evidence"], ["[URL]"]
        )

    def test_reject_source_origin_identifier(self):
        with_origin = record()
        with_origin["judgment"]["questions"][0]["evidence"] = [
            "[poison:3] fabricated text"
        ]
        with self.assertRaises(RAGArtifactError):
            normalize_record(with_origin, task())

    def test_clean_audit_must_have_zero_poison(self):
        bad = record(clean=True)
        bad["audit"]["poison_documents_injected"] = 1
        bad["audit"]["realized_poison_fraction"] = 1 / 101
        with self.assertRaises(RAGArtifactError):
            normalize_record(bad, task(clean=True))

    def test_realized_fraction_is_checked(self):
        bad = record()
        bad["audit"]["realized_poison_fraction"] = 0.99
        with self.assertRaises(RAGArtifactError):
            normalize_record(bad, task())


if __name__ == "__main__":
    unittest.main()
