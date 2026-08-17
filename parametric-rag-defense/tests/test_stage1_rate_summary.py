from __future__ import annotations

import unittest

from scripts.summarize_stage1_rag_scan import merge_scans


def scan(*, split: str = "development", model: str = "model_a", condition: str, rate: float):
    return {
        "evaluation_schema_version": 1,
        "split": split,
        "rates": [rate],
        "models": {model: {"levels": {condition: {"predictions": {}}}}},
    }


class Stage1RateSummaryTests(unittest.TestCase):
    def test_merge_scans_sorts_disjoint_rates(self):
        merged = merge_scans(
            [
                scan(condition="fact2fiction_p0.01", rate=0.01),
                scan(condition="fact2fiction_p0.0025", rate=0.0025),
            ]
        )
        self.assertEqual(merged["rates"], [0.0025, 0.01])
        self.assertEqual(
            list(merged["models"]["model_a"]["levels"]),
            ["fact2fiction_p0.0025", "fact2fiction_p0.01"],
        )

    def test_merge_scans_rejects_duplicate_conditions(self):
        duplicate = scan(condition="fact2fiction_p0.01", rate=0.01)
        with self.assertRaisesRegex(ValueError, "Duplicate scan condition"):
            merge_scans([duplicate, duplicate])

    def test_merge_scans_rejects_different_splits(self):
        with self.assertRaisesRegex(ValueError, "different splits"):
            merge_scans(
                [
                    scan(condition="fact2fiction_p0.01", rate=0.01),
                    scan(
                        split="locked_test",
                        condition="fact2fiction_p0.0025",
                        rate=0.0025,
                    ),
                ]
            )


if __name__ == "__main__":
    unittest.main()
