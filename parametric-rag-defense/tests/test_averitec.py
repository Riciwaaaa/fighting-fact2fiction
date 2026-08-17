from __future__ import annotations

import unittest

from parametric_rag_defense.averitec import (
    expand_poison_blueprints,
    poison_document_count,
    realized_poison_fraction,
)


class AVeriTeCTests(unittest.TestCase):
    def test_released_poison_count_convention(self):
        self.assertEqual(poison_document_count(823, 0.001), 1)
        self.assertEqual(poison_document_count(823, 0.01), 8)
        self.assertEqual(poison_document_count(823, 0.04), 34)
        self.assertEqual(poison_document_count(823, 0.08), 71)

    def test_realized_fraction_uses_final_pool(self):
        self.assertAlmostEqual(realized_poison_fraction(823, 8), 8 / 831)

    def test_blueprint_expansion_is_exact_and_deterministic(self):
        blueprints = [
            {"query": "q1", "text": "text 1", "weight": 1},
            {"query": "q2", "text": "text 2", "weight": 3},
        ]
        first = expand_poison_blueprints(blueprints, 7, seed=101)
        second = expand_poison_blueprints(blueprints, 7, seed=101)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 7)
        self.assertEqual([item["document_id"] for item in first], [f"poison:{i}" for i in range(7)])


if __name__ == "__main__":
    unittest.main()
