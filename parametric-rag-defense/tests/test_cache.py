from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from parametric_rag_defense.cache import (
    CacheConflictError,
    CacheCorruptionError,
    LLMCache,
    LLMRequest,
)


def request(**changes):
    values = {
        "stage": "stage1_internal",
        "provider": "test-provider",
        "model": "test-model-v1",
        "prompt_id": "internal_claim",
        "prompt_version": "v1",
        "messages": [{"role": "user", "content": "Is the claim true?"}],
        "parameters": {"temperature": 0, "max_tokens": 100},
        "response_format": {"type": "json_object"},
    }
    values.update(changes)
    return LLMRequest(**values)


class LLMCacheTests(unittest.TestCase):
    def test_key_is_stable_across_mapping_order(self):
        first = request(parameters={"temperature": 0, "max_tokens": 100})
        second = request(parameters={"max_tokens": 100, "temperature": 0})
        self.assertEqual(first.key, second.key)

    def test_response_relevant_fields_change_key(self):
        base = request()
        self.assertNotEqual(base.key, request(model="other-model").key)
        self.assertNotEqual(base.key, request(prompt_version="v2").key)
        self.assertNotEqual(base.key, request(parameters={"temperature": 0.2}).key)

    def test_store_load_and_cache_hit(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = LLMCache(directory)
            calls = 0

            def compute():
                nonlocal calls
                calls += 1
                return {"raw_text": "{}", "parsed": {"verdict": "Refuted"}}

            first, first_hit = cache.get_or_compute(request(), compute, metadata={"claim_id": 7})
            second, second_hit = cache.get_or_compute(request(), compute, metadata={"claim_id": 7})
            self.assertFalse(first_hit)
            self.assertTrue(second_hit)
            self.assertEqual(calls, 1)
            self.assertEqual(first, second)
            self.assertEqual(second["metadata"]["claim_id"], 7)

    def test_immutable_response_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = LLMCache(directory)
            cache.store(request(), {"parsed": {"verdict": "Refuted"}})
            with self.assertRaises(CacheConflictError):
                cache.store(request(), {"parsed": {"verdict": "Supported"}})

    def test_corrupt_entry_fails_loudly(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = LLMCache(directory)
            path = cache.entry_path(request().key)
            path.parent.mkdir(parents=True)
            path.write_text("{not-json", encoding="utf-8")
            with self.assertRaises(CacheCorruptionError):
                cache.load(request())

    def test_secret_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            request(parameters={"api_key": "do-not-cache"})

    def test_entry_is_valid_json_and_no_temporary_file_remains(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = LLMCache(directory)
            cache.store(request(), {"raw_text": "answer", "usage": {"input_tokens": 12}})
            path = cache.entry_path(request().key)
            self.assertEqual(json.loads(path.read_text())["key"], request().key)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()

