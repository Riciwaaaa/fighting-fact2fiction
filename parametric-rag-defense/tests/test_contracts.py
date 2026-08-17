from __future__ import annotations

import json
import unittest

from parametric_rag_defense.contracts import (
    ContractError,
    parse_internal_judgment,
    validate_rag_judgment,
)


class InternalContractTests(unittest.TestCase):
    def valid(self):
        return {
            "verdict": "Refuted",
            "confidence": 0.8,
            "knowledge_basis": "direct_recall",
            "rationale": "The central event is a documented fabrication.",
            "decisive_propositions": ["The alleged document was fabricated."],
            "premise_concerns": [],
        }

    def test_plain_and_fenced_json(self):
        payload = json.dumps(self.valid())
        self.assertEqual(parse_internal_judgment(payload)["verdict"], "Refuted")
        self.assertEqual(parse_internal_judgment(f"```json\n{payload}\n```")["confidence"], 0.8)

    def test_extra_fields_fail(self):
        value = self.valid()
        value["gold_label"] = "Refuted"
        with self.assertRaises(ContractError):
            parse_internal_judgment(json.dumps(value))

    def test_non_recall_is_a_basis_not_a_forced_verdict(self):
        value = self.valid()
        value["knowledge_basis"] = "insufficient_knowledge"
        value["verdict"] = "Not Enough Evidence"
        parsed = parse_internal_judgment(json.dumps(value))
        self.assertEqual(parsed["knowledge_basis"], "insufficient_knowledge")

    def test_invalid_confidence_fails(self):
        value = self.valid()
        value["confidence"] = 1.2
        with self.assertRaises(ContractError):
            parse_internal_judgment(json.dumps(value))


class RAGContractTests(unittest.TestCase):
    def valid(self):
        return {
            "verdict": "Supported",
            "confidence": 0.75,
            "justification": "The adopted answers consistently support the claim.",
            "questions": [
                {
                    "question": "Did the event occur?",
                    "status": "answered",
                    "answer": "Yes.",
                    "selected_rank": 1,
                    "evidence": ["A source-normalized evidence excerpt."],
                }
            ],
        }

    def test_valid_rag_artifact(self):
        self.assertEqual(validate_rag_judgment(self.valid())["confidence"], 0.75)

    def test_answered_question_requires_answer(self):
        value = self.valid()
        value["questions"][0]["answer"] = None
        with self.assertRaises(ContractError):
            validate_rag_judgment(value)

    def test_rag_extra_fields_fail(self):
        value = self.valid()
        value["attack_label"] = True
        with self.assertRaises(ContractError):
            validate_rag_judgment(value)


if __name__ == "__main__":
    unittest.main()
