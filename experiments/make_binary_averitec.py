"""
Generate a binary (Supported/Refuted only) subset of AVeriTeC's dev.json.

Claim ids in this pipeline are just array positions in dev.json, and every cached
poison-attack artifact (attack_results/.../{resources,knns}/*.pkl) is keyed by that
position. So filtering can't just drop rows and re-enumerate -- each retained entry
gets an explicit "orig_id" field recording its original dev.json position, and
AVeriTeCBinary (infact/eval/benchmark.py) reads that field back as the claim id
instead of re-enumerating. This keeps every existing cached attack valid against
the new file.

Non-destructive: reads DEFAME/data/AVeriTeC/dev.json, writes dev_binary.json next
to it. dev.json itself is untouched.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "DEFAME" / "data" / "AVeriTeC" / "dev.json"
DST = REPO_ROOT / "DEFAME" / "data" / "AVeriTeC" / "dev_binary.json"

BINARY_LABELS = {"Supported", "Refuted"}


def main():
    with open(SRC) as f:
        data = json.load(f)

    out = []
    for orig_id, entry in enumerate(data):
        if entry.get("label") in BINARY_LABELS:
            entry = dict(entry)
            entry["orig_id"] = orig_id
            out.append(entry)

    with open(DST, "w") as f:
        json.dump(out, f, indent=2)

    counts = {}
    for entry in data:
        counts[entry.get("label")] = counts.get(entry.get("label"), 0) + 1

    print(f"Read {len(data)} claims from {SRC}")
    print(f"Label distribution: {counts}")
    print(f"Kept {len(out)} Supported/Refuted claims -> {DST}")


if __name__ == "__main__":
    main()
