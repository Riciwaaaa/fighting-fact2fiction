from __future__ import annotations

import unittest

from scripts.summarize_evidence_signal import (
    choose_endpoint,
    endpoint_counts,
    evidence_label,
    project_full_system,
)


def judgment(
    direction: str,
    *,
    support: list[str] | None = None,
    refutation: list[str] | None = None,
    conflict: bool = False,
) -> dict:
    return {
        "overall_assessment": {
            "direction": direction,
            "direct_support_cluster_ids": support or [],
            "direct_refutation_cluster_ids": refutation or [],
            "evidence_conflict": conflict,
        }
    }


class EvidenceSignalSummaryTests(unittest.TestCase):
    def test_strict_label_requires_unopposed_direct_cluster(self):
        value = judgment("supports", support=["cluster_01"])
        self.assertEqual(evidence_label(value), "Supported")
        self.assertEqual(evidence_label(value, strict=True), "Supported")
        self.assertIsNone(evidence_label(judgment("supports"), strict=True))
        self.assertIsNone(
            evidence_label(
                judgment(
                    "supports",
                    support=["cluster_01"],
                    refutation=["cluster_02"],
                    conflict=True,
                ),
                strict=True,
            )
        )

    def test_endpoint_choice_uses_direction_then_declared_default(self):
        row = {
            "retrieval_prediction": "Supported",
            "memory_prediction": "Refuted",
            "judgment": judgment("supports"),
        }
        self.assertEqual(choose_endpoint(row, default="memory"), "retrieval")
        row["judgment"] = judgment("mixed")
        self.assertEqual(choose_endpoint(row, default="memory"), "memory")
        self.assertEqual(choose_endpoint(row, default="retrieval"), "retrieval")

    def test_endpoint_counts_use_exact_outcome_cells(self):
        curve = {
            "models": {},
            "aggregate": {
                "levels": {
                    "attack": {
                        "paired_claims": 10,
                        "endpoint_outcomes": {
                            "both_correct": 4,
                            "rag_only_correct": 2,
                            "internal_only_correct": 3,
                            "neither_correct": 1,
                        },
                    }
                }
            },
        }
        self.assertEqual(
            endpoint_counts(curve, condition="attack"),
            {"rows": 10, "rag_correct": 6, "memory_correct": 7},
        )

    def test_full_projection_changes_only_disagreements(self):
        summary = {
            "loose_memory_default": {"net_correct_change_vs_default": -2},
            "strict_memory_default": {"net_correct_change_vs_default": 1},
            "loose_rag_default": {"net_correct_change_vs_default": 3},
            "strict_rag_default": {"net_correct_change_vs_default": 0},
        }
        projected = project_full_system(
            summary, {"rows": 100, "rag_correct": 70, "memory_correct": 75}
        )
        self.assertEqual(projected["loose_memory_default"]["correct"], 73)
        self.assertEqual(projected["strict_memory_default"]["correct"], 76)
        self.assertEqual(projected["loose_rag_default"]["correct"], 73)
        self.assertEqual(projected["strict_rag_default"]["correct"], 70)


if __name__ == "__main__":
    unittest.main()
