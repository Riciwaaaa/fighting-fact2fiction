from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from parametric_rag_defense.matrix import (
    all_attack_conditions,
    build_internal_tasks,
    build_rag_tasks,
    select_tier_conditions,
)


class Stage1MatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(Path("configs/stage1_matrix.json").read_text())

    def test_attack_strengths_follow_papers(self):
        conditions = all_attack_conditions(self.config)
        ids = {condition["id"] for condition in conditions}
        self.assertEqual(len(conditions), 21)
        self.assertIn("clean", ids)
        self.assertIn("poisonedrag_n1", ids)
        self.assertIn("poisonedrag_n5", ids)
        self.assertIn("poisonedrag_n10", ids)
        self.assertIn("fact2fiction_p0.001", ids)
        self.assertIn("fact2fiction_p0.01", ids)
        self.assertIn("fact2fiction_p0.16", ids)

    def test_internal_outputs_do_not_multiply_by_attack_strength(self):
        tasks = build_internal_tasks(self.config, "development", [0, 1])
        self.assertEqual(len(tasks), 4 * 2 * 3)
        self.assertEqual(len({task["task_key"] for task in tasks}), len(tasks))

    def test_workload_summary_separates_target_and_enabled_models(self):
        summary = json.loads(Path("configs/stage1_task_summary.json").read_text())
        self.assertEqual(summary["model_count"], 4)
        self.assertEqual(summary["enabled_model_count"], 3)
        self.assertEqual(summary["internal_task_counts"]["development"], 1200)
        self.assertEqual(summary["enabled_internal_task_counts"]["development"], 900)
        self.assertTrue(summary["rag_counts_are_prefilter_upper_bounds"])

    def test_active_splits_are_fact2fiction_binary_candidates(self):
        split = json.loads(Path("configs/splits/stage1.json").read_text())
        self.assertEqual(split["development"]["count"], 100)
        self.assertEqual(split["locked_test"]["count"], 100)
        self.assertEqual(
            set(split["development"]["label_counts"]), {"Supported", "Refuted"}
        )
        self.assertEqual(
            set(split["locked_test"]["label_counts"]), {"Supported", "Refuted"}
        )
        development = set(split["development"]["claim_ids"])
        locked = set(split["locked_test"]["claim_ids"])
        diagnostic = set(split["four_label_diagnostic"]["claim_ids"])
        self.assertEqual(len(development), 100)
        self.assertEqual(len(locked), 100)
        self.assertEqual(len(diagnostic), 20)
        self.assertFalse(development & locked)
        self.assertFalse(development & diagnostic)
        self.assertFalse(locked & diagnostic)
        self.assertTrue(split["development"]["unique_internal_prompts"])
        self.assertTrue(split["locked_test"]["unique_internal_prompts"])
        self.assertTrue(split["four_label_diagnostic"]["unique_internal_prompts"])

    def test_internal_prompt_matches_frozen_digest(self):
        prompt_path = Path(self.config["prompt"]["path"])
        lock_path = prompt_path.with_suffix(prompt_path.suffix + ".sha256")
        expected = lock_path.read_text(encoding="utf-8").strip().split()[0]
        observed = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
        self.assertEqual(observed, expected)

    def test_development_sweep_is_preregistered_four_level_scan(self):
        conditions = select_tier_conditions(self.config, "development_sweep")
        self.assertEqual(
            [condition["id"] for condition in conditions],
            [
                "clean",
                "fact2fiction_p0.001",
                "fact2fiction_p0.01",
                "fact2fiction_p0.04",
                "fact2fiction_p0.08",
            ],
        )
        tasks = build_rag_tasks(self.config, "development_sweep", [0])
        self.assertEqual(len(tasks), 4 * 5)

    def test_intermediate_sweep_fills_the_weak_attack_gap(self):
        conditions = select_tier_conditions(self.config, "development_intermediate_sweep")
        self.assertEqual(
            [condition["id"] for condition in conditions],
            [
                "clean",
                "fact2fiction_p0.0025",
                "fact2fiction_p0.005",
                "fact2fiction_p0.0075",
            ],
        )
        tasks = build_rag_tasks(self.config, "development_intermediate_sweep", [0])
        self.assertEqual(len(tasks), 4 * 4)

    def test_clean_task_is_not_repeated_across_attack_seeds(self):
        tasks = build_rag_tasks(self.config, "locked_primary", [0])
        clean = [task for task in tasks if task["condition"]["id"] == "clean"]
        self.assertEqual(len(clean), 4)
        self.assertTrue(all(task["attack_seed"] is None for task in clean))


if __name__ == "__main__":
    unittest.main()
