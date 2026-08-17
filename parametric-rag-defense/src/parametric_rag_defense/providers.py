"""Minimal provider adapters that return cache-safe response metadata."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

from .cache import LLMRequest

PROVIDER_URLS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "nvidia_prod": "https://inference-api.nvidia.com/v1/chat/completions",
    "nvidia_dev": "https://inference-api-dev.nvidia.com/v1/chat/completions",
}
PROVIDER_KEY_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "nvidia_prod": "NVIDIA_API_KEY",
    "nvidia_dev": "NVIDIA_API_KEY",
}


class ProviderError(RuntimeError):
    """Raised when an inference provider does not return a usable completion."""


class ProviderOutputTruncated(ProviderError):
    """Raised for a deterministic token-budget failure that should not be retried unchanged."""


def _sanitize_error_detail(detail: str, credential: str) -> str:
    sanitized = detail.replace(credential, "<redacted>")
    return re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "<redacted-key>", sanitized)


def openai_compatible_complete(
    request: LLMRequest,
    *,
    api_key: str | None = None,
    endpoint: str | None = None,
    attempts: int = 4,
    timeout_seconds: float = 180,
) -> dict[str, Any]:
    """Issue one non-streaming OpenAI-compatible chat request.

    Credentials are read at call time and never inserted into ``LLMRequest`` or the returned cache
    record. Provider reasoning/hidden-chain-of-thought fields are deliberately not persisted.
    """

    if request.provider not in PROVIDER_URLS:
        raise ProviderError(f"Unsupported provider: {request.provider}")
    credential_env = PROVIDER_KEY_ENV[request.provider]
    credential = api_key or os.environ.get(credential_env)
    if not credential:
        raise ProviderError(f"{credential_env} is not set")
    provider_url = endpoint or PROVIDER_URLS[request.provider]

    payload: dict[str, Any] = {
        "model": request.model,
        "messages": list(request.messages),
        **dict(request.parameters),
    }
    payload["stream"] = False
    if request.response_format is not None:
        payload["response_format"] = dict(request.response_format)
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {credential}",
        "Content-Type": "application/json",
        "User-Agent": "parametric-rag-defense/0.1",
    }

    delay = 2.0
    last_error: Exception | None = None
    attempts_made = 0
    for attempt in range(attempts):
        attempts_made = attempt + 1
        started = time.perf_counter()
        try:
            http_request = urllib.request.Request(
                provider_url,
                data=body,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(http_request, timeout=timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
            latency_ms = (time.perf_counter() - started) * 1000
            choice = result["choices"][0]
            message = choice["message"]
            content = message.get("content") or ""
            if not isinstance(content, str) or not content.strip():
                finish_reason = choice.get("finish_reason")
                if finish_reason == "length":
                    raise ProviderOutputTruncated(
                        "Provider exhausted max_tokens before emitting visible content"
                    )
                raise ProviderError("Provider returned an empty completion")
            return {
                "raw_text": content,
                "provider_response_id": result.get("id"),
                "provider_model": result.get("model"),
                "finish_reason": choice.get("finish_reason"),
                "usage": result.get("usage") or {},
                "latency_ms": latency_ms,
            }
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            detail = _sanitize_error_detail(detail, credential)
            last_error = ProviderError(f"HTTP {exc.code}: {detail}")
            if 400 <= exc.code < 500 and exc.code not in {408, 429}:
                break
            if attempt == attempts - 1:
                break
            time.sleep(delay)
            delay *= 2
        except ProviderOutputTruncated as exc:
            last_error = exc
            break
        except (KeyError, TypeError, ValueError, urllib.error.URLError, ProviderError) as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(delay)
            delay *= 2
    detail = f": {last_error}" if last_error is not None else ""
    raise ProviderError(
        f"{request.provider} call failed after {attempts_made} attempt(s){detail}"
    ) from last_error


def openrouter_complete(request: LLMRequest, **kwargs: Any) -> dict[str, Any]:
    """Backward-compatible OpenRouter wrapper."""

    if request.provider != "openrouter":
        raise ProviderError("openrouter_complete requires request.provider='openrouter'")
    return openai_compatible_complete(request, **kwargs)
