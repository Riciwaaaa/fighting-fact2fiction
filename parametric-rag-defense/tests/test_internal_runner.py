from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from parametric_rag_defense.cache import LLMRequest


SPEC = importlib.util.spec_from_file_location(
    "run_stage1_internal", Path("scripts/run_stage1_internal.py")
)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class InternalRunnerTests(unittest.TestCase):
    def test_contract_retry_has_a_distinct_auditable_key(self):
        request = LLMRequest(
            stage="stage1_internal",
            provider="test",
            model="model",
            prompt_id="prompt",
            prompt_version="v1+sha256:digest",
            messages=[{"role": "user", "content": "Return JSON."}],
            parameters={"seed": 29},
            response_format={"type": "json_object"},
        )
        retry = RUNNER.contract_retry_request(request, 1)
        self.assertNotEqual(retry.key, request.key)
        self.assertEqual(retry.parameters, request.parameters)
        self.assertEqual(retry.messages[:-1], request.messages)
        self.assertIn("contract-retry:1", retry.prompt_version)

    def test_manifest_merge_prunes_pairs_outside_active_scope(self):
        previous = {
            "outputs": [
                {"claim_id": 1, "seed": 11, "cache_key": "old-active"},
                {"claim_id": 2, "seed": 11, "cache_key": "old-removed"},
            ]
        }
        rows = [{"claim_id": 1, "seed": 29, "cache_key": "new-active"}]
        merged = RUNNER.merge_manifest_rows(
            previous,
            rows,
            compatible=True,
            allowed_pairs={(1, 11), (1, 29)},
        )
        self.assertEqual(
            [(row["claim_id"], row["seed"]) for row in merged], [(1, 11), (1, 29)]
        )

    def test_incompatible_manifest_is_archived_even_when_scope_is_unchanged(self):
        previous = {
            "requested_claims": [1],
            "prompt_sha256": "old",
            "outputs": [{"claim_id": 1, "seed": 11, "cache_key": "old"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "model.json"
            archived = RUNNER.archive_superseded_manifest(
                manifest_path, previous, [1], compatible=False
            )
            self.assertIsNotNone(archived)
            assert archived is not None
            self.assertEqual(json.loads(archived.read_text(encoding="utf-8")), previous)

    def test_compatible_same_scope_manifest_is_not_archived(self):
        previous = {"requested_claims": [1], "outputs": []}
        with tempfile.TemporaryDirectory() as directory:
            archived = RUNNER.archive_superseded_manifest(
                Path(directory) / "model.json", previous, [1], compatible=True
            )
            self.assertIsNone(archived)


if __name__ == "__main__":
    unittest.main()
