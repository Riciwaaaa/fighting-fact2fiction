#!/usr/bin/env python3
"""Reject credential-shaped strings in Git-tracked files."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

PATTERNS = [
    re.compile(rb"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(rb"(?:NVIDIA|OPENROUTER)_API_KEY\s*=\s*[^\s$<{]+"),
]


def main() -> None:
    result = subprocess.run(
        ["git", "ls-files", "-z"], check=True, stdout=subprocess.PIPE
    )
    files = [Path(value.decode()) for value in result.stdout.split(b"\0") if value]
    findings: list[str] = []
    for path in files:
        if not path.is_file():
            continue
        data = path.read_bytes()
        for pattern in PATTERNS:
            if pattern.search(data):
                findings.append(f"{path}: matches {pattern.pattern.decode()}")
    if findings:
        print("Tracked-secret scan FAILED")
        for finding in findings:
            print(f"- {finding}")
        raise SystemExit(1)
    print(f"Tracked-secret scan passed: {len(files)} tracked paths")


if __name__ == "__main__":
    main()
