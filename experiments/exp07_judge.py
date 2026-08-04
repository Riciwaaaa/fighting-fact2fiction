"""
Experiment 07 -- the record-blind judge, run over a finished verdict.

Given a claim and two candidate verdicts, and nothing else, decide which is right. No retrieved
record, no sub-questions, no debate. It exists because it was the control arm of a debate
experiment (commit a7f40ae) and beat every arm that actually held a debate: 72/99 against the
poisoned baseline's 56/99 and the merged pipeline's 68/99. The debate machinery is gone; this is
what was left standing.

`--source` picks which finished verdict is put to it, and that is the only thing that varies:

    P     the poisoned fact-check's verdict      -- already measured: 72/99
    PM    the merged pipeline's verdict          -- P and PM differ on 18 of the 99 claims, so
                                                    that is the most this can move
    C     the clean fact-check's verdict
    M     the retrieval-free pipeline's verdict

The judge is told which of the two verdicts came from the side with documents, and it leans that
way: on the P source it kept the starting verdict 81 times out of 99. So this is not a claim-only
classifier -- the starting verdict is doing work -- but most of what it does is decide when to
override.

The prompt is byte-identical to the debate run's judge, dead wording about transcripts and all,
so these numbers sit on the same scale as the arms already measured.

Reads verdicts_<source>_dropempty.json from both run dirs. Writes naive_<source>.json.
Run under /home/ubuntu/.venv312/bin/python3.12.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
DEFAULT_DIRS = [EXPERIMENTS_DIR / "runs" / "07_verdict_40claim",
                EXPERIMENTS_DIR / "runs" / "08_verdict_59claim"]

sys.path.insert(0, str(EXPERIMENTS_DIR))
from fusion_common import call_json, set_model  # noqa: E402
from exp07_prompts import JUDGE_PROMPT, valid_judge  # noqa: E402

LABELS = ("supported", "refuted")

# What the transcript slot held on the arm where nobody spoke. Kept verbatim so the numbers stay
# comparable with that run.
NO_DEBATE = "(no debate was held; decide from the Claim and the two verdicts alone)"


def counter_of(verdict: str):
    """The opposite label, or None if the starting verdict is not one of the two.

    InFact's Judge can emit a label outside the class list it was given: extract_verdict tries
    `Label(answer)` first (judge.py:90), and that succeeds for any member of the Label enum, so a
    judge restricted to Supported/Refuted can still return "not enough information" and have it
    recorded. It happened once in 792 verdicts. There is no opposite of NEI in a binary space, so
    such a claim is skipped and counted rather than assigned a guess.
    """
    other = [x for x in LABELS if x != verdict.lower()]
    return other[0] if len(other) == 1 else None


def judge_one(rec):
    claim, verdict = rec["claim"], rec["verdict"].lower()
    counter = counter_of(verdict)
    if counter is None:
        return {"claim_id": rec["claim_id"], "claim": claim,
                "gold_label": rec["gold_label"], "start_verdict": verdict,
                "counter_verdict": None, "start_correct": rec["correct"],
                "judge_verdict": None, "correct": None, "changed": None,
                "judge_reason": None, "judge_failed": False, "off_label_start": True}
    adj = call_json(JUDGE_PROMPT
                    .replace("[CLAIM]", claim)
                    .replace("[VERDICT]", verdict)
                    .replace("[COUNTER_VERDICT]", counter)
                    .replace("[TRANSCRIPT]", NO_DEBATE),
                    lambda d: valid_judge(d, verdict, counter))
    final = ((adj or {}).get("verdict") or "").strip().strip("`").lower() or None
    return {
        "claim_id": rec["claim_id"],
        "claim": claim,
        "gold_label": rec["gold_label"],
        "start_verdict": verdict,
        "counter_verdict": counter,
        "start_correct": rec["correct"],
        "judge_verdict": final,
        "correct": (final == str(rec["gold_label"]).lower()) if final else None,
        "changed": (final != verdict) if final else None,
        "judge_reason": (adj or {}).get("reason"),
        "judge_failed": final is None,
        "off_label_start": False,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dirs", type=str, default=",".join(str(d) for d in DEFAULT_DIRS))
    ap.add_argument("--source", type=str, default="PM")
    ap.add_argument("--claims", type=str, default=None)
    ap.add_argument("--model", type=str, default="xiaomi/mimo-v2.5-pro")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out-dir", type=str, default=str(DEFAULT_DIRS[0]))
    args = ap.parse_args()

    set_model(args.model)
    out_dir = Path(args.out_dir).resolve()

    starts = {}
    for d in [Path(x) for x in args.run_dirs.split(",")]:
        p = d / f"verdicts_{args.source}_dropempty.json"
        if not p.exists():
            sys.exit(f"{p} not found")
        for r in json.load(open(p)):
            if r["claim_id"] in starts:
                sys.exit(f"claim {r['claim_id']} appears in more than one run dir")
            starts[r["claim_id"]] = r

    want = ({int(x) for x in args.claims.split(",")} if args.claims else None)
    cids = sorted(c for c in starts if want is None or c in want)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        out = list(ex.map(lambda c: judge_one(starts[c]), cids))

    for r in out:
        print(f"[{args.source} {r['claim_id']}] {r['start_verdict']} -> {r['judge_verdict']}"
              f" ({'changed' if r['changed'] else 'held'}) | gold {r['gold_label']} "
              f"{'OK' if r['correct'] else 'WRONG'}", flush=True)

    k = sum(1 for r in out if r["correct"])
    k0 = sum(1 for r in out if r["start_correct"])
    fixed = sum(1 for r in out if r["correct"] and not r["start_correct"])
    broke = sum(1 for r in out if r["start_correct"] and r["correct"] is False)
    bad = sum(1 for r in out if r["judge_failed"])
    off = sum(1 for r in out if r.get("off_label_start"))
    print(f"\nNAIVE-{args.source}: {k}/{len(out)} correct (started at {k0}/{len(out)}) "
          f"| fixed {fixed}, broke {broke}"
          + (f" | JUDGE FAILED {bad}" if bad else "")
          + (f" | {off} skipped: starting verdict outside the binary label space" if off else "")
          + f" ({time.perf_counter() - t0:.0f}s)", flush=True)

    with open(out_dir / f"naive_{args.source}.json", "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
