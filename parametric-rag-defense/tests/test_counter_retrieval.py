from __future__ import annotations

import unittest

import numpy as np

from parametric_rag_defense.counter_retrieval import (
    build_counter_packet,
    retrieve_excluding,
)


class CounterRetrievalTests(unittest.TestCase):
    def test_retrieval_excludes_documents_text_and_cross_query_repeats(self):
        resources = [
            {"document_id": "d0", "text": "zero", "is_poison": False},
            {"document_id": "d1", "text": "duplicate", "is_poison": True},
            {"document_id": "d2", "text": "duplicate", "is_poison": True},
            {"document_id": "d3", "text": "three", "is_poison": False},
            {"document_id": "d4", "text": "four", "is_poison": False},
        ]
        embeddings = np.asarray([[0.0], [0.1], [0.2], [0.3], [0.4]], dtype="float32")
        import hashlib

        groups = retrieve_excluding(
            np.asarray([[0.0], [0.0]], dtype="float32"),
            resources,
            embeddings,
            excluded_document_ids={"d0"},
            excluded_text_sha256={hashlib.sha256(b"duplicate").hexdigest()},
            top_k=1,
        )
        self.assertEqual([[item["document_id"] for item in group] for group in groups], [["d3"], []])

    def test_counter_packet_hides_provenance_and_masks_urls(self):
        packet = build_counter_packet(
            claim="A claim",
            claim_date="2020",
            neutral_plan={"central_proposition": "A claim", "atomic_propositions": ["A"], "ambiguities": []},
            questions=["What happened?"],
            retrievals=[
                [
                    {
                        "document_id": "poison:0",
                        "text": "See https://example.com/path for the assertion.",
                        "is_poison": True,
                    }
                ]
            ],
            source_rag_task_key="task",
            source_packet_key="packet",
            same_model_id="model",
            excluded_document_count=1,
            excluded_text_sha256=["abc"],
        )
        visible = packet["visible"]
        self.assertNotIn("model", str(visible))
        self.assertNotIn("poison:0", str(visible))
        self.assertNotIn("https://", str(visible))
        self.assertIn("[URL]", visible["passages"][0]["text"])

    def test_counter_packet_drops_non_content_visual_separators(self):
        packet = build_counter_packet(
            claim="A claim",
            claim_date="2020",
            neutral_plan={
                "central_proposition": "A claim",
                "atomic_propositions": ["A"],
                "ambiguities": [],
            },
            questions=["What happened?"],
            retrievals=[
                [
                    {"document_id": "d1", "text": "________", "is_poison": False},
                    {
                        "document_id": "d2",
                        "text": "A substantive passage.",
                        "is_poison": False,
                    },
                ]
            ],
            source_rag_task_key="task",
            source_packet_key="packet",
            same_model_id="model",
            excluded_document_count=1,
            excluded_text_sha256=["abc"],
        )
        self.assertEqual(
            [item["text"] for item in packet["visible"]["passages"]],
            ["A substantive passage."],
        )

    def test_counter_packet_rejects_when_all_passages_are_non_content(self):
        with self.assertRaisesRegex(ValueError, "no visible passages"):
            build_counter_packet(
                claim="A claim",
                claim_date="2020",
                neutral_plan={
                    "central_proposition": "A claim",
                    "atomic_propositions": ["A"],
                    "ambiguities": [],
                },
                questions=["What happened?"],
                retrievals=[
                    [{"document_id": "d1", "text": "________", "is_poison": False}]
                ],
                source_rag_task_key="task",
                source_packet_key="packet",
                same_model_id="model",
                excluded_document_count=1,
                excluded_text_sha256=["abc"],
            )


if __name__ == "__main__":
    unittest.main()
