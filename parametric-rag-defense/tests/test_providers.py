from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from parametric_rag_defense.cache import LLMRequest
from parametric_rag_defense.providers import ProviderError, openai_compatible_complete


def request():
    return LLMRequest(
        stage="test",
        provider="nvidia_prod",
        model="test-model",
        prompt_id="test",
        prompt_version="v1",
        messages=[{"role": "user", "content": "Return READY"}],
        parameters={"max_tokens": 16},
    )


class FakeResponse:
    def __init__(self, value):
        self.payload = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class ProviderTests(unittest.TestCase):
    @patch("parametric_rag_defense.providers.urllib.request.urlopen")
    def test_successful_completion_is_cache_safe(self, urlopen):
        urlopen.return_value = FakeResponse(
            {
                "id": "response-1",
                "model": "resolved-model",
                "choices": [
                    {"message": {"content": "READY", "reasoning": "hidden"}, "finish_reason": "stop"}
                ],
                "usage": {"total_tokens": 3},
            }
        )
        result = openai_compatible_complete(request(), api_key="unit-test-credential", attempts=1)
        self.assertEqual(result["raw_text"], "READY")
        self.assertNotIn("reasoning", result)
        self.assertNotIn("unit-test-credential", json.dumps(result))

    @patch("parametric_rag_defense.providers.urllib.request.urlopen")
    def test_length_truncation_is_not_retried_unchanged(self, urlopen):
        urlopen.return_value = FakeResponse(
            {
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
            }
        )
        with self.assertRaisesRegex(ProviderError, "after 1 attempt"):
            openai_compatible_complete(request(), api_key="unit-test-credential", attempts=4)
        self.assertEqual(urlopen.call_count, 1)

    @patch("parametric_rag_defense.providers.urllib.request.urlopen")
    def test_http_error_redacts_credentials(self, urlopen):
        credential = "unit-test-credential-value"
        urlopen.side_effect = urllib.error.HTTPError(
            "https://example.test",
            401,
            "unauthorized",
            {},
            io.BytesIO(f"credential={credential}".encode()),
        )
        with self.assertRaises(ProviderError) as raised:
            openai_compatible_complete(request(), api_key=credential, attempts=1)
        self.assertNotIn(credential, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
