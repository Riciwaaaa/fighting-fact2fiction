"""Content-addressed, immutable cache for paid LLM calls.

The cache key covers the complete inference request. Runtime metadata such as claim IDs can be
attached to an entry, but it does not change the key unless it changes the actual messages or model
configuration. Cache records deliberately exclude credentials and hidden reasoning traces.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

CACHE_SCHEMA_VERSION = 1
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "openrouter_api_key",
    "nvidia_api_key",
}


class CacheError(RuntimeError):
    """Base class for cache failures."""


class CacheCorruptionError(CacheError):
    """Raised when a cache path exists but is not a valid entry."""


class CacheConflictError(CacheError):
    """Raised when an immutable key is reused with a different response."""


def _assert_no_secrets(value: Any, path: str = "request") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text.lower() in _SECRET_KEYS or key_text.lower().endswith("_api_key"):
                raise ValueError(f"Secret-like field is forbidden in cached requests: {path}.{key_text}")
            _assert_no_secrets(child, f"{path}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_no_secrets(child, f"{path}[{index}]")


def assert_no_secrets(value: Any, path: str = "value") -> None:
    """Public guard for any persisted experimental artifact."""

    _assert_no_secrets(value, path)


def canonical_json(value: Any) -> str:
    """Serialize JSON data deterministically and reject NaN/Infinity."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True)
class LLMRequest:
    """Every field that can change an LLM response and therefore the cache key."""

    stage: str
    provider: str
    model: str
    prompt_id: str
    prompt_version: str
    messages: Sequence[Mapping[str, Any]]
    parameters: Mapping[str, Any] = field(default_factory=dict)
    response_format: Mapping[str, Any] | None = None
    cache_schema_version: int = CACHE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("stage", "provider", "model", "prompt_id", "prompt_version"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"LLMRequest.{name} cannot be empty")
        if not self.messages:
            raise ValueError("LLMRequest.messages cannot be empty")
        _assert_no_secrets(self.to_dict())
        canonical_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def key(self) -> str:
        payload = canonical_json(self.to_dict()).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class LLMCache:
    """Filesystem cache with atomic writes and a per-request inter-process lock."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def entry_path(self, key: str) -> Path:
        return self.root / "entries" / key[:2] / f"{key}.json"

    def lock_path(self, key: str) -> Path:
        return self.root / "locks" / key[:2] / f"{key}.lock"

    def load(self, request: LLMRequest) -> dict[str, Any] | None:
        path = self.entry_path(request.key)
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CacheCorruptionError(f"Unreadable cache entry: {path}") from exc

        if not isinstance(entry, dict):
            raise CacheCorruptionError(f"Cache entry is not an object: {path}")
        if entry.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
            raise CacheCorruptionError(f"Unsupported cache schema at {path}")
        if entry.get("key") != request.key:
            raise CacheCorruptionError(f"Cache key mismatch at {path}")
        if entry.get("request") != request.to_dict():
            raise CacheCorruptionError(f"Cached request mismatch at {path}")
        if not isinstance(entry.get("response"), dict):
            raise CacheCorruptionError(f"Cached response is missing or invalid at {path}")
        return entry

    def store(
        self,
        request: LLMRequest,
        response: Mapping[str, Any],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store one immutable response and return the complete cache entry."""

        _assert_no_secrets(response, "response")
        _assert_no_secrets(metadata or {}, "metadata")
        entry = {
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "key": request.key,
            "created_at": datetime.now(UTC).isoformat(),
            "request": request.to_dict(),
            "response": dict(response),
            "metadata": dict(metadata or {}),
        }
        canonical_json(entry)

        existing = self.load(request)
        if existing is not None:
            if existing["response"] != entry["response"]:
                raise CacheConflictError(
                    f"Refusing to overwrite immutable cache response for {request.key}"
                )
            return existing

        path = self.entry_path(request.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{request.key}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(entry, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return entry

    def get_or_compute(
        self,
        request: LLMRequest,
        compute: Callable[[], Mapping[str, Any]],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Load an entry or compute it once under an inter-process lock.

        Returns ``(entry, cache_hit)``. The cache is checked again after taking the lock so that
        parallel workers do not duplicate an expensive provider request.
        """

        existing = self.load(request)
        if existing is not None:
            return existing, True

        lock_path = self.lock_path(request.key)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            existing = self.load(request)
            if existing is not None:
                return existing, True
            response = compute()
            if not isinstance(response, Mapping):
                raise TypeError("LLM compute callback must return a mapping")
            return self.store(request, response, metadata=metadata), False
