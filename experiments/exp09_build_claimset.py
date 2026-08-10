"""
Assemble a run directory for a claim set out of whatever earlier runs already computed.

Passes A, B and D (question posing, clean retrieval, model-only answering) depend only on the
claim -- not on the poison rate, not on which experiment asked for them -- so a claim already
processed by an earlier run never needs redoing. Those runs were carved up by other concerns
(a 40/59 split, a 50/50 sample, a 16-claim backfill), so the artifacts for one claim set end up
scattered across several directories. This gathers them.

MERGING IS PER CLAIM, ALL-OR-NOTHING. Pass A generates its questions with an LLM, so re-running
it on the same claim gives a *different* question set -- measured here, all 34 claims that appear
in more than one run have different questions in each. Taking a claim's questions from one run
and its answers from another would pair answers with questions they never answered, silently
destroying the one property every later pass relies on: that clean retrieval, poisoned retrieval
and the model-only reasoner all answered the same questions for that claim. So each claim is
sourced whole, from the first run in priority order that has every requested file for it.

Pass C is poison-rate specific: only merge it from directories that used the same rate, which
`--with-poisoned` gates.

Prints the claims still missing, which is what to hand to `--claims` next.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS = REPO_ROOT / "experiments" / "runs"

SHARED = ["questions.json", "answers_clean.json", "answers_model_only.json"]
# Priority order: most recent complete pipeline first. Only matters for claims several runs
# processed; whichever wins, that claim is taken whole from it.
DEFAULT_SOURCES = ["10_verdict_84claim", "08_verdict_59claim", "07_verdict_40claim",
                   "06_symmetric_conflict", "11_cm_only_16claim"]


def binary_prefix(n: int) -> list:
    """The first `n` Supported/Refuted claims in dev order."""
    dev = json.load(open(REPO_ROOT / "DEFAME" / "data" / "AVeriTeC" / "dev.json"))
    return [i for i, x in enumerate(dev) if x["label"] in ("Supported", "Refuted")][:n]


def load_run(run: str, files: list) -> dict:
    """file -> {claim_id: record} for one run dir; missing files give an empty mapping."""
    out = {}
    for fname in files:
        p = RUNS / run / fname
        out[fname] = ({r["claim_id"]: r for r in json.load(open(p))} if p.exists() else {})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=str, required=True)
    ap.add_argument("--n-claims", type=int, default=100)
    ap.add_argument("--from", dest="sources", type=str, default=",".join(DEFAULT_SOURCES))
    ap.add_argument("--with-poisoned", action="store_true",
                    help="Also copy answers_poisoned.json, from each claim's chosen run. Only "
                         "pass this when every source directory used the same poison rate.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    files = SHARED + (["answers_poisoned.json"] if args.with_poisoned else [])
    want = binary_prefix(args.n_claims)
    print(f"target: {len(want)} claims, ids {min(want)}-{max(want)}")
    print(f"a claim is sourced whole from one run, requiring: {', '.join(SHARED)}\n")

    loaded = {run: load_run(run, files) for run in sources}

    # The run is chosen on the rate-independent artifacts alone. The poisoned answers then come
    # from THAT run or not at all: sourcing them from a run that posed different questions would
    # attach poisoned answers to questions they never answered. A claim with no poisoned answers
    # in its chosen run is not dropped -- for claims Fact2Fiction cannot attack there will never
    # be any, and the poisoned arms are backfilled from the clean ones downstream.
    chosen, merged = {}, {f: {} for f in files}
    for cid in want:
        for run in sources:
            if all(cid in loaded[run][f] for f in SHARED):
                chosen[cid] = run
                for f in files:
                    if cid in loaded[run][f]:
                        merged[f][cid] = loaded[run][f][cid]
                break

    missing = [c for c in want if c not in chosen]
    print(f"rate-independent artifacts (A/B/D) found: {len(chosen)}/{len(want)}")
    for run, n in Counter(chosen.values()).most_common():
        print(f"    {n:3d} from {run}")
    print(f"\nneed passes A/B/D run from scratch: {len(missing)}")
    if missing:
        print(f"  --claims {','.join(map(str, missing))}")

    if args.with_poisoned:
        pois = merged["answers_poisoned.json"]
        lack = [c for c in sorted(chosen) if c not in pois]
        print(f"\npoisoned answers carried over: {len(pois)}/{len(chosen)}")
        print(f"  claims whose chosen run has no pass C: {len(lack)}")
        if lack:
            print(f"    {','.join(map(str, lack))}")
            print("    (run pass C for whichever of these Fact2Fiction actually attacked; the "
                  "rest have no poisoned corpus and get backfilled from the clean arm)")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    for fname, got in merged.items():
        with open(out_dir / fname, "w") as f:
            json.dump([got[c] for c in sorted(got)], f, indent=2)
        print(f"wrote {out_dir / fname} ({len(got)} claims)")
    with open(out_dir / "claim_sources.json", "w") as f:
        json.dump({"claims": want, "sourced_from": {str(k): v for k, v in chosen.items()},
                   "missing": missing}, f, indent=2)
    print(f"wrote {out_dir / 'claim_sources.json'}")


if __name__ == "__main__":
    main()
