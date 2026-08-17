from __future__ import annotations

import unittest

from parametric_rag_defense.contracts import ContractError
from parametric_rag_defense.neutral_firewall import endpoint_prediction, parse_neutral_plan


class NeutralFirewallTests(unittest.TestCase):
    def plan(self) -> dict:
        return {
            "central_proposition": "The event occurred in 2020.",
            "support_probe": "A dated record places the event in 2020.",
            "refutation_probe": "The event occurred in a different year.",
            "temporal_scope": "Through December 2020.",
            "ambiguities": [],
        }

    def test_neutral_plan_contract(self):
        self.assertEqual(parse_neutral_plan(self.plan()), self.plan())

    def test_neutral_plan_rejects_verdict_leak(self):
        with self.assertRaises(ContractError):
            parse_neutral_plan({**self.plan(), "verdict": "Supported"})

    def test_neutral_plan_caps_ambiguities(self):
        with self.assertRaises(ContractError):
            parse_neutral_plan({**self.plan(), "ambiguities": ["a", "b", "c", "d"]})

    def test_endpoint_prediction_copies_only_existing_endpoint(self):
        labels = {"retrieval": "Supported", "memory": "Refuted"}
        self.assertEqual(endpoint_prediction(labels, "retrieval"), "Supported")
        self.assertEqual(endpoint_prediction(labels, "memory"), "Refuted")
        with self.assertRaises(ValueError):
            endpoint_prediction(labels, "synthesize")


if __name__ == "__main__":
    unittest.main()
