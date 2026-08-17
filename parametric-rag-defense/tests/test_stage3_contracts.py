from __future__ import annotations

import json
import unittest

from parametric_rag_defense.contracts import ContractError
from parametric_rag_defense.stage3_contracts import parse_claim_arbiter, parse_evidence_critic


class Stage3ContractTests(unittest.TestCase):
    def test_critic_contract(self):
        value = {
            "evidence_direction": "refutes_claim",
            "coverage": "partial",
            "coherence": "consistent",
            "claim_premise_risk": "medium",
            "summary": "The shown excerpts refute the central event.",
            "decisive_evidence": ["The event record is described as fabricated."],
            "unresolved_points": [],
        }
        self.assertEqual(parse_evidence_critic(json.dumps(value)), value)

    def test_arbiter_requires_fallback_verdict_for_escalation(self):
        value = {
            "route": "escalate",
            "final_verdict": "Not Enough Evidence",
            "confidence": 0.4,
            "decisive_conflict": "The occurrence of the event remains unresolved.",
            "epistemic_assessment": "Neither assessment establishes the decisive fact.",
            "reason_codes": ["unresolved_decisive_conflict"],
            "pivotal_propositions": ["The event occurred."],
            "rationale": "The available support is insufficient.",
        }
        self.assertEqual(parse_claim_arbiter(json.dumps(value)), value)

    def test_rejects_unknown_reason_and_source_metadata(self):
        value = {
            "route": "trust_retrieval",
            "final_verdict": "Supported",
            "confidence": 0.8,
            "decisive_conflict": "none",
            "epistemic_assessment": "The evidence is coherent.",
            "reason_codes": ["made_up_code"],
            "pivotal_propositions": [],
            "rationale": "See https://example.test",
        }
        with self.assertRaises(ContractError):
            parse_claim_arbiter(json.dumps(value))

    def test_unambiguous_qwen_rationate_field_alias(self):
        value = {
            "route": "trust_memory",
            "final_verdict": "Refuted",
            "confidence": 0.8,
            "decisive_conflict": "The endpoints disagree.",
            "epistemic_assessment": "Memory has direct recall.",
            "reason_codes": ["memory_direct_recall"],
            "pivotal_propositions": [],
            "rationate": "The remembered fact refutes the claim.",
        }
        parsed = parse_claim_arbiter(json.dumps(value))
        self.assertNotIn("rationate", parsed)
        self.assertEqual(parsed["rationale"], value["rationate"])

    def test_rationate_alias_does_not_mask_extra_fields(self):
        value = {
            "route": "trust_memory",
            "final_verdict": "Refuted",
            "confidence": 0.8,
            "decisive_conflict": "The endpoints disagree.",
            "epistemic_assessment": "Memory has direct recall.",
            "reason_codes": ["memory_direct_recall"],
            "pivotal_propositions": [],
            "rationale": "A rationale.",
            "rationate": "A conflicting typo field.",
        }
        with self.assertRaises(ContractError):
            parse_claim_arbiter(json.dumps(value))


if __name__ == "__main__":
    unittest.main()
