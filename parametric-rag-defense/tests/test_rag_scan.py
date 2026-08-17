from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("run_stage1_rag_scan", Path("scripts/run_stage1_rag_scan.py"))
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class RAGScanContractTests(unittest.TestCase):
    def test_retrieval_top_k_is_configurable_with_historical_fallback(self):
        self.assertEqual(
            RUNNER.configured_retrieval_top_k(
                {
                    "rag_pipeline": {"retrieval_top_k": 10},
                    "attacks": {"poisonedrag": {"retrieval_top_k": 5}},
                }
            ),
            10,
        )
        self.assertEqual(
            RUNNER.configured_retrieval_top_k(
                {"rag_pipeline": {}, "attacks": {"poisonedrag": {"retrieval_top_k": 5}}}
            ),
            5,
        )
        with self.assertRaises(ValueError):
            RUNNER.configured_retrieval_top_k({"rag_pipeline": {"retrieval_top_k": 0}})

    def test_url_masking_is_limited_to_url(self):
        self.assertEqual(
            RUNNER.mask_urls("See https://example.com/path and retain this"),
            "See [URL] and retain this",
        )

    def test_neutral_evidence_ids_do_not_reveal_origin(self):
        self.assertEqual(RUNNER.neutral_evidence_id(2, 4), "evidence_q3_r4")
        RUNNER.assert_neutral_victim_prompt("Use evidence_q3_r4. URL: [URL]")

    def test_victim_prompt_guard_rejects_origin_and_url(self):
        with self.assertRaises(RuntimeError):
            RUNNER.assert_neutral_victim_prompt("source poison:3")
        with self.assertRaises(RuntimeError):
            RUNNER.assert_neutral_victim_prompt("https://example.com")

    def test_plan_contract_requires_ten_questions(self):
        payload = {
            "questions": [
                {"question": f"question {index}", "query": f"query {index}"}
                for index in range(10)
            ]
        }
        self.assertEqual(len(RUNNER.parse_plan(json.dumps(payload))["questions"]), 10)

    def test_answer_contract_orders_by_question_index(self):
        payload = {
            "answers": [
                {"question_index": 1, "status": "none", "answer": None, "selected_rank": None},
                {"question_index": 0, "status": "answered", "answer": "yes", "selected_rank": 1},
            ]
        }
        parsed = RUNNER.parse_answers(json.dumps(payload), [2, 1])
        self.assertEqual([item["question_index"] for item in parsed["answers"]], [0, 1])

    def test_answer_for_zero_fresh_results_is_deterministically_dropped(self):
        payload = {
            "answers": [
                {"question_index": 0, "status": "answered", "answer": "borrowed", "selected_rank": 1}
            ]
        }
        parsed = RUNNER.parse_answers(json.dumps(payload), [0])
        self.assertEqual(
            parsed["answers"][0],
            {"question_index": 0, "status": "none", "answer": None, "selected_rank": None},
        )

    def test_invalid_answer_rank_falls_back_to_first_result(self):
        payload = {
            "answers": [
                {"question_index": 0, "status": "answered", "answer": "grounded", "selected_rank": None}
            ]
        }
        parsed = RUNNER.parse_answers(json.dumps(payload), [3])
        self.assertEqual(parsed["answers"][0]["selected_rank"], 1)

    def test_blueprint_contract(self):
        payload = {
            "blueprints": [
                {"question_index": 0, "query": "query", "text": "corpus", "weight": 7}
            ]
        }
        parsed = RUNNER.parse_blueprints(json.dumps(payload), 1, 10)
        self.assertEqual(parsed["blueprints"][0]["weight"], 7)


if __name__ == "__main__":
    unittest.main()
