#!/usr/bin/env python3
"""Call every configured NVIDIA model once and cache the connectivity result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parametric_rag_defense.cache import LLMCache, LLMRequest
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.providers import openai_compatible_complete


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument("--models", help="Optional comma-separated model IDs")
    args = parser.parse_args()

    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    load_dotenv(config_path.parent.parent / ".env")
    selected = set(args.models.split(",")) if args.models else None
    models = [model for model in config["models"] if selected is None or model["id"] in selected]
    cache = LLMCache(Path(config["cache_root"]).resolve())
    failed = False

    for model in models:
        request = LLMRequest(
            stage="provider_smoke",
            provider=model["provider"],
            model=model["model"],
            prompt_id="provider_smoke",
            prompt_version="v1",
            messages=[
                {"role": "system", "content": "Follow the user's format exactly."},
                {"role": "user", "content": "Reply with exactly the single word READY."},
            ],
            # Reasoning-capable Qwen endpoints may consume a substantial part of the limit before
            # emitting visible content; use the provider example's 1024-token allowance.
            parameters={
                "temperature": 0.2,
                "top_p": 0.7,
                "max_tokens": 1024,
                **model.get("request_parameters", {}),
            },
        )
        try:
            entry, cache_hit = cache.get_or_compute(
                request,
                lambda: openai_compatible_complete(request),
                metadata={"model_id": model["id"], "purpose": "connectivity_smoke"},
            )
            text = entry["response"]["raw_text"].strip().replace("\n", " ")
            print(
                f"model={model['id']} provider={model['provider']} cache_hit={cache_hit} "
                f"response={text[:80]!r}"
            )
        except Exception as exc:
            failed = True
            print(f"model={model['id']} provider={model['provider']} FAILED: {exc}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
