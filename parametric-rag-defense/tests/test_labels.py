from __future__ import annotations

import unittest

from parametric_rag_defense.labels import accuracy, canonical_label, deterministic_majority, macro_f1


class LabelTests(unittest.TestCase):
    def test_dataset_conflict_label_is_mapped(self):
        mapping = {"Conflicting Evidence/Cherrypicking": "Conflicting Evidence"}
        self.assertEqual(
            canonical_label("Conflicting Evidence/Cherrypicking", mapping),
            "Conflicting Evidence",
        )

    def test_majority_and_deterministic_tie(self):
        self.assertEqual(deterministic_majority(["Refuted", "Refuted", "Supported"]), "Refuted")
        self.assertEqual(deterministic_majority(["Refuted", "Supported"]), "Supported")

    def test_metrics(self):
        gold = ["Supported", "Refuted", "Conflicting Evidence", "Not Enough Evidence"]
        self.assertEqual(accuracy(gold, gold), 1.0)
        self.assertEqual(macro_f1(gold, gold), 1.0)

    def test_binary_macro_f1_does_not_average_absent_classes(self):
        gold = ["Supported", "Refuted"]
        self.assertEqual(macro_f1(gold, gold), 1.0)
        self.assertEqual(macro_f1(gold, ["Not Enough Evidence", "Refuted"]), 0.5)


if __name__ == "__main__":
    unittest.main()
