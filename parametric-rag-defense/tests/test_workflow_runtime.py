from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from parametric_rag_defense.cache import LLMCache, LLMRequest
from parametric_rag_defense.contracts import ContractError
from parametric_rag_defense.workflow_runtime import execute_cached, render


class WorkflowRuntimeTests(unittest.TestCase):
    def test_render_allows_literal_braces_in_inserted_evidence(self):
        evidence = 'scraped template text: {{hitsCtrl.values.hits}}'
        self.assertEqual(
            render("Evidence:\n{{EVIDENCE_PACKET}}", {"EVIDENCE_PACKET": evidence}),
            f"Evidence:\n{evidence}",
        )

    def test_render_rejects_unresolved_template_marker(self):
        with self.assertRaisesRegex(ValueError, "MISSING"):
            render("{{PRESENT}} {{MISSING}}", {"PRESENT": "ok"})

    def test_contract_exhaustion_preserves_all_attempt_receipts(self):
        request = LLMRequest(
            stage="test_stage",
            provider="test_provider",
            model="test_model",
            prompt_id="test_prompt",
            prompt_version="v1",
            messages=[{"role": "user", "content": "Return JSON."}],
        )

        def reject(_: str) -> dict:
            raise ContractError("invalid test response")

        with tempfile.TemporaryDirectory() as directory, patch(
            "parametric_rag_defense.workflow_runtime.openai_compatible_complete",
            return_value={"raw_text": "truncated"},
        ):
            with self.assertRaises(ContractError) as raised:
                execute_cached(
                    cache=LLMCache(Path(directory)),
                    request=request,
                    parser=reject,
                    metadata={"model_id": "test_model_id"},
                    contract_name="test contract",
                    retries=2,
                )

        receipts = raised.exception.receipts
        self.assertEqual(len(receipts), 3)
        self.assertTrue(all(receipt["contract_ok"] is False for receipt in receipts))
        self.assertEqual(len({receipt["cache_key"] for receipt in receipts}), 3)


if __name__ == "__main__":
    unittest.main()
