# llm_client.py
#
# WHY a separate file for the LLM call:
#   The graph node just calls `call_glm(prompt)`. If you later want to swap
#   the model or change API provider, you only touch this file, not the graph.

import os
import time
from dataclasses import dataclass

from openai import OpenAI  # OpenRouter uses the OpenAI-compatible API

# ── Result container ───────────────────────────────────────────────────────────
@dataclass
class LLMResponse:
    content: str        # the model's answer text (everything after <think>)
    thinking: str       # the thinking / reasoning trace (empty string if not returned)
    latency_ms: float   # wall-clock time for the API call in milliseconds
    model_name: str     # model ID echoed back from the response


def build_client() -> OpenAI:
    """
    Create an OpenAI client pointed at OpenRouter.

    WHY OpenAI SDK + OpenRouter:
      OpenRouter exposes an OpenAI-compatible REST API, so we reuse the
      well-maintained openai Python package instead of writing raw HTTP.
      The only differences are the base_url and extra_body params below.
    """
    api_key = os.environ["OPENROUTER_API_KEY"]  # set in .env
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )


# Module-level singleton so we don't recreate the client on every call
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = build_client()
    return _client


def call_glm(prompt: str) -> LLMResponse:
    """
    Send a prompt to GLM via OpenRouter and return the full response.

    Thinking mode
    ─────────────
    GLM-Z1 (and other "thinking" models on OpenRouter) supports chain-of-thought
    reasoning that is streamed in a separate field before the final answer.

    HOW to enable it on OpenRouter:
      Pass `"include_reasoning": True` inside `extra_body`.
      WHY extra_body: OpenRouter extends the OpenAI request schema; parameters
      not in the standard spec go here so the SDK doesn't reject them.

    WHERE the thinking trace appears in the response:
      `response.choices[0].message.reasoning`  ← OpenRouter puts it here
      If that attribute is missing (model doesn't support it), we fall back
      to parsing <think>...</think> tags from the content string.
    """
    model_name = os.environ["MODEL_NAME"]
    client = _get_client()

    t0 = time.perf_counter()

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        # No `reasoning`/`thinking` params — let the model use its own defaults
        # (xiaomi/mimo-v2.5-pro needs no extra reasoning config). If a model that
        # requires an explicit reasoning object is used, pass it as an object
        # (e.g. extra_body={"reasoning": {"effort": "max"}}) — a bare string 400s.
    )

    latency_ms = (time.perf_counter() - t0) * 1000

    message = response.choices[0].message
    content = message.content or ""

    # ── Extract thinking trace ─────────────────────────────────────────────
    # Try the dedicated `reasoning` attribute first (OpenRouter standard).
    # Fall back to stripping <think>...</think> from content (some models
    # embed thinking inline instead of in a separate field).
    thinking = ""
    if hasattr(message, "reasoning") and message.reasoning:
        thinking = message.reasoning
    else:
        # Fallback: parse <think> tags if present in content
        import re
        think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
        if think_match:
            thinking = think_match.group(1).strip()
            # Remove the <think> block from content so parse_label sees clean text
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    return LLMResponse(
        content=content,
        thinking=thinking,
        latency_ms=latency_ms,
        model_name=response.model,
    )
