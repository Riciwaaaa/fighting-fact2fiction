from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Stage234ProtocolTests(unittest.TestCase):
    def test_grouped_design_validation_split_is_balanced_and_disjoint(self):
        split = json.loads(
            (ROOT / "configs/splits/stage234_development.json").read_text(encoding="utf-8")
        )
        design = set(split["method_design"]["claim_ids"])
        validation = set(split["development_validation"]["claim_ids"])
        parent = json.loads((ROOT / "configs/splits/stage1.json").read_text(encoding="utf-8"))
        self.assertEqual(len(design), 60)
        self.assertEqual(len(validation), 40)
        self.assertFalse(design & validation)
        self.assertEqual(design | validation, set(parent["development"]["claim_ids"]))
        self.assertEqual(split["method_design"]["label_counts"], {
            "Refuted": 30, "Supported": 30
        })
        self.assertEqual(split["development_validation"]["label_counts"], {
            "Refuted": 20, "Supported": 20
        })

    def test_stage3_prompts_match_frozen_digests(self):
        for filename in ("stage3_evidence_critic_v1.md", "stage3_claim_arbiter_v1.md"):
            path = ROOT / "prompts" / filename
            expected = path.with_suffix(path.suffix + ".sha256").read_text().split()[0]
            observed = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(observed, expected)

    def test_aligned_prompts_match_frozen_digests(self):
        for path in (
            ROOT / "prompts/aligned_router_endpoint_v1.md",
            ROOT / "prompts/aligned_router_evidence_v1.md",
            ROOT / "prompts/aligned_proposition_check_v1.md",
            ROOT / "prompts/aligned_final_arbiter_v1.md",
        ):
            expected = path.with_suffix(path.suffix + ".sha256").read_text().strip()
            observed = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(observed, expected)

    def test_aligned_primary_roles_are_same_model(self):
        workflow = json.loads((ROOT / "configs/stage234_workflow.json").read_text())
        aligned = workflow["aligned_stage3"]
        self.assertIn("exactly the same model", aligned["primary_roles"])
        self.assertEqual(aligned["prediction_contract"].split(";")[0], "Copy the provisional endpoint verdict")
        self.assertEqual(workflow["aligned_stage4"]["activation"], "Only when the same model's RAG and closed-book endpoint verdicts disagree.")

    def test_workflow_uses_only_repaired_stage1_namespace(self):
        config = json.loads((ROOT / "configs/stage234_workflow.json").read_text())
        self.assertEqual(config["source"]["rag_artifact_namespace"], "stage1_rag_v1.2")
        self.assertEqual(config["source"]["rag_evidence_contract"], "neutral-source-v1")
        self.assertTrue(config["freeze_policy"]["gold_joined_only_in_evaluation_scripts"])


if __name__ == "__main__":
    unittest.main()
