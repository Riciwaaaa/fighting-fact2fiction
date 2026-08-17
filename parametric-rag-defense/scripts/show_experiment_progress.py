#!/usr/bin/env python3
"""Print current snapshots for all locally recorded experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path("artifacts/runs/progress"),
        help="directory containing experiment snapshot JSON files",
    )
    args = parser.parse_args()
    rows = []
    for path in sorted(args.root.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "experiment_id": value["experiment_id"],
                "status": value["status"],
                "phase": value["phase"],
                "updated_at": value["updated_at"],
                "counts": value.get("counts", {}),
                "last_event": value.get("last_event"),
            }
        )
    print(json.dumps({"experiments": rows}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
