"""Shared cached-call runtime for structured experimental workflows."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

from .cache import LLMCache, LLMRequest
from .contracts import ContractError
from .providers import openai_compatible_complete

Parser = Callable[[str], dict[str, Any]]


def prompt_version(path: Path, identifier: str) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode()).hexdigest()
    lock_path = path.with_suffix(path.suffix + ".sha256")
    if lock_path.exists():
        expected = lock_path.read_text(encoding="utf-8").strip().split()[0]
        if expected != digest:
            raise RuntimeError(
                f"Prompt digest mismatch for {path}: expected {expected}, observed {digest}"
            )
    return text, f"{identifier}+sha256:{digest}"


def render(template: str, replacements: dict[str, str]) -> str:
    template_markers = set(re.findall(r"\{\{([^{}]+)\}\}", template))
    unresolved = template_markers - set(replacements)
    if unresolved:
        raise ValueError(
            "Unresolved placeholder remains in workflow prompt: "
            + ", ".join(sorted(unresolved))
        )
    result = template
    for marker, value in replacements.items():
        result = result.replace("{{" + marker + "}}", value)
    return result


def _parsed_response(parser: Parser, response: dict[str, Any]) -> dict[str, Any]:
    try:
        response["parsed"] = parser(response["raw_text"])
        response["contract_ok"] = True
    except ContractError as exc:
        response["parsed"] = None
        response["contract_ok"] = False
        response["contract_error"] = str(exc)
    return response


def _retry_request(request: LLMRequest, attempt: int, contract_name: str) -> LLMRequest:
    return LLMRequest(
        stage=request.stage,
        provider=request.provider,
        model=request.model,
        prompt_id=request.prompt_id,
        prompt_version=f"{request.prompt_version}+contract-retry:{attempt}",
        messages=[
            *request.messages,
            {
                "role": "user",
                "content": (
                    f"Format-repair attempt {attempt}: return the {contract_name} again as exactly "
                    "one JSON object satisfying every requested field and enum."
                ),
            },
        ],
        parameters=request.parameters,
        response_format=request.response_format,
    )


def execute_cached(
    *,
    cache: LLMCache,
    request: LLMRequest,
    parser: Parser,
    metadata: dict[str, Any],
    contract_name: str,
    retries: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    active_request = request
    receipts: list[dict[str, Any]] = []
    for attempt in range(retries + 1):
        entry, cache_hit = cache.get_or_compute(
            active_request,
            lambda current=active_request: _parsed_response(
                parser, openai_compatible_complete(current)
            ),
            metadata={**metadata, "contract_attempt": attempt},
        )
        try:
            parsed = parser(entry["response"]["raw_text"])
            contract_error = None
        except ContractError as exc:
            parsed = None
            contract_error = str(exc)
        receipts.append(
            {
                "attempt": attempt,
                "cache_key": active_request.key,
                "cache_hit": cache_hit,
                "contract_ok": parsed is not None,
                "contract_error": contract_error,
            }
        )
        if parsed is not None:
            return parsed, receipts
        if attempt < retries:
            active_request = _retry_request(request, attempt + 1, contract_name)
    error = ContractError(f"{contract_name} failed after {retries + 1} attempts")
    # Preserve the immutable attempt identities for an explicitly authorized fail-closed
    # resolution.  Callers still receive an exception and must opt in to handling it.
    error.receipts = receipts
    raise error


def store_immutable_output(root: Path, key: str, value: dict[str, Any]) -> tuple[Path, bool]:
    path = root / key[:2] / f"{key}.json"
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != serialized:
            raise RuntimeError(f"Refusing to overwrite conflicting workflow output: {path}")
        return path, True
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{key}.", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path, False
