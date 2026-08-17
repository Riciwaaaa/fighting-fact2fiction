"""Small durable experiment ledger for long, resumable collections."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .cache import assert_no_secrets, canonical_json

_EXPERIMENT_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,79}$")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ExperimentLedger:
    """Maintain a current snapshot plus an append-only JSONL event history."""

    def __init__(self, root: str | Path, experiment_id: str, *, description: str) -> None:
        if not _EXPERIMENT_ID.fullmatch(experiment_id):
            raise ValueError(f"invalid experiment_id: {experiment_id!r}")
        self.root = Path(root)
        self.experiment_id = experiment_id
        self.snapshot_path = self.root / f"{experiment_id}.json"
        self.events_path = self.root / f"{experiment_id}.events.jsonl"
        self.lock = threading.Lock()
        if self.snapshot_path.exists():
            self.snapshot = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            if self.snapshot.get("experiment_id") != experiment_id:
                raise RuntimeError(f"progress ledger identity mismatch: {self.snapshot_path}")
        else:
            timestamp = _now()
            self.snapshot = {
                "progress_schema_version": 1,
                "experiment_id": experiment_id,
                "description": description,
                "status": "initialized",
                "phase": "setup",
                "created_at": timestamp,
                "updated_at": timestamp,
                "counts": {},
                "artifacts": {},
                "last_event": None,
            }
            _atomic_json(self.snapshot_path, self.snapshot)

    def update(
        self,
        *,
        status: str,
        phase: str,
        event: str,
        counts: Mapping[str, int] | None = None,
        artifacts: Mapping[str, str] | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if status not in {"initialized", "running", "complete", "failed", "blocked"}:
            raise ValueError(f"invalid experiment status: {status}")
        payload = {
            "event_schema_version": 1,
            "experiment_id": self.experiment_id,
            "timestamp": _now(),
            "status": status,
            "phase": phase,
            "event": event,
            "counts": dict(counts or {}),
            "artifacts": dict(artifacts or {}),
            "details": dict(details or {}),
        }
        assert_no_secrets(payload, "progress_event")
        canonical_json(payload)
        with self.lock:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(canonical_json(payload) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self.snapshot.update(
                {
                    "status": status,
                    "phase": phase,
                    "updated_at": payload["timestamp"],
                    "counts": payload["counts"],
                    "artifacts": payload["artifacts"],
                    "last_event": event,
                }
            )
            _atomic_json(self.snapshot_path, self.snapshot)
        return payload
