import json
import unittest

from parametric_rag_defense.contracts import ContractError
from parametric_rag_defense.stage4_v2 import (
    parse_adjudicator_text,
    parse_architect_text,
    validate_action_verdict,
)


class Stage4V2ContractTests(unittest.TestCase):
    def test_architect_requires_both_roles(self):
        value = {
            "disagreement_summary": "Endpoints conflict.",
            "propositions": [
                {
                    "id": "P1",
                    "role": "claim_core",
                    "text": "The claim is accurate.",
                    "effect_if_supported": "supports_claim",
                    "effect_if_refuted": "refutes_claim",
                    "faithfulness_check": "Matches the claim.",
                },
                {
                    "id": "P2",
                    "role": "discriminator",
                    "text": "The decisive event occurred by the stated date.",
                    "effect_if_supported": "supports_claim",
                    "effect_if_refuted": "refutes_claim",
                    "faithfulness_check": "Preserves date and subject.",
                },
            ],
            "planning_rationale": "The checks are complementary.",
        }
        parsed = parse_architect_text(json.dumps(value))
        self.assertEqual([item["role"] for item in parsed["propositions"]], ["claim_core", "discriminator"])

    def test_architect_rejects_duplicate_role(self):
        value = {
            "disagreement_summary": "Endpoints conflict.",
            "propositions": [
                {
                    "id": identifier,
                    "role": "claim_core",
                    "text": "A factual proposition.",
                    "effect_if_supported": "supports_claim",
                    "effect_if_refuted": "refutes_claim",
                    "faithfulness_check": "Faithful.",
                }
                for identifier in ("P1", "P2")
            ],
            "planning_rationale": "Rationale.",
        }
        with self.assertRaises(ContractError):
            parse_architect_text(json.dumps(value))

    def test_selection_action_must_copy_endpoint(self):
        value = {
            "action": "select_memory",
            "verdict": "Supported",
            "confidence": 0.8,
            "anchor_assessment": "Memory is the anchor.",
            "proposition_assessment": "Checks support it.",
            "endpoint_assessment": "Memory is stronger.",
            "rationale": "Select memory.",
        }
        judgment = parse_adjudicator_text(json.dumps(value))
        validate_action_verdict(
            judgment, retrieval_verdict="Supported", memory_verdict="Supported"
        )
        with self.assertRaises(ContractError):
            validate_action_verdict(
                judgment, retrieval_verdict="Supported", memory_verdict="Refuted"
            )

    def test_internal_action_must_copy_synthesis(self):
        value = {
            "action": "select_internal",
            "verdict": "Refuted",
            "confidence": 0.8,
            "anchor_assessment": "The internal challenge is stronger.",
            "proposition_assessment": "Checks converge.",
            "endpoint_assessment": "Endpoints conflict.",
            "rationale": "Select internal.",
        }
        judgment = parse_adjudicator_text(json.dumps(value))
        validate_action_verdict(
            judgment,
            retrieval_verdict="Supported",
            memory_verdict="Not Enough Evidence",
            internal_verdict="Refuted",
        )


if __name__ == "__main__":
    unittest.main()
