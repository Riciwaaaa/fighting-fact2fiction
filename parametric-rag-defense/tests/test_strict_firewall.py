from __future__ import annotations

import unittest

from parametric_rag_defense.strict_firewall import strict_firewalled_selection


class StrictFirewallTests(unittest.TestCase):
    def select(self, support: str, counter: str, requested: str = "retrieval") -> dict:
        return strict_firewalled_selection(
            endpoint_labels={"retrieval": "Supported", "memory": "Refuted"},
            support_judgment={
                "verdict": support,
                "knowledge_basis": "direct_recall",
                "decisive_propositions": ["fact a"],
            },
            counter_judgment={
                "verdict": counter,
                "knowledge_basis": "direct_recall",
                "decisive_propositions": ["fact b"],
            },
            selector_judgment={"selected_endpoint": requested},
        )

    def test_accepts_retrieval_only_under_convergence(self):
        result = self.select("Supported", "Supported")
        self.assertEqual(result["selected_endpoint"], "retrieval")
        self.assertEqual(result["prediction"], "Supported")
        self.assertFalse(result["semantic_guard_applied"])

    def test_rejects_conflicting_retrieval_selection(self):
        result = self.select("Supported", "Refuted")
        self.assertEqual(result["selected_endpoint"], "memory")
        self.assertEqual(result["prediction"], "Refuted")
        self.assertTrue(result["semantic_guard_applied"])

    def test_rejects_insufficient_retrieval_selection(self):
        result = self.select("Not Enough Evidence", "Supported")
        self.assertEqual(result["selected_endpoint"], "memory")
        self.assertTrue(result["semantic_guard_applied"])

    def test_rejects_merely_inferential_convergence(self):
        result = strict_firewalled_selection(
            endpoint_labels={"retrieval": "Refuted", "memory": "Supported"},
            support_judgment={
                "verdict": "Refuted",
                "knowledge_basis": "inference",
                "decisive_propositions": ["inferred proposition"],
            },
            counter_judgment={
                "verdict": "Refuted",
                "knowledge_basis": "direct_recall",
                "decisive_propositions": ["recalled proposition"],
            },
            selector_judgment={"selected_endpoint": "retrieval"},
        )
        self.assertTrue(result["retrieval_convergence"])
        self.assertFalse(result["direct_factual_support"])
        self.assertEqual(result["selected_endpoint"], "memory")

    def test_memory_request_is_unchanged(self):
        result = self.select("Supported", "Supported", requested="memory")
        self.assertEqual(result["selected_endpoint"], "memory")
        self.assertFalse(result["semantic_guard_applied"])

    def test_rejects_unknown_endpoint(self):
        with self.assertRaises(ValueError):
            self.select("Supported", "Supported", requested="synthesize")


if __name__ == "__main__":
    unittest.main()
