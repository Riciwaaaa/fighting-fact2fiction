#!/usr/bin/env python3
"""Verify that the frozen Stage C candidate files still match their pre-validation hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--freeze", type=Path, default=Path("configs/stage4_candidate_freeze.json")
    )
    args = parser.parse_args()
    freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
    failures = []
    observed = {}
    for name, expected in freeze["frozen_files_sha256"].items():
        path = Path(name)
        if not path.is_file():
            failures.append(f"missing frozen file: {name}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        observed[name] = digest
        if digest != expected:
            failures.append(f"hash mismatch: {name}")
    result = {
        "status": "pass" if not failures else "fail",
        "method": freeze["method"],
        "primary_model": freeze["primary_model"],
        "checked_files": len(observed),
        "failures": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
