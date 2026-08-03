"""
Pool the verdict arms across run directories into one table.

The 99 claims with cached poison artifacts were processed in two batches: 40 claims
(runs/07_verdict_40claim) and the remaining 59 (runs/08_verdict_59claim). The batches share
everything that matters -- the same passes, prompts, model, label space and record format -- so
their verdicts pool directly, claim by claim.

ONE ROUND FROM EACH. The 40-claim batch was judged twice per arm and the 59-claim batch once,
and mixing those would weight the first 40 claims double. The pooled table therefore uses round 1
everywhere. The 40-claim second round is not discarded: it is the measurement of how unstable the
judge is, and it is reported separately, because a difference between arms is only meaningful
against that.

Reads verdicts_<arm>_dropempty.json from each run dir. Writes exp06_pooled_report.md next to the
first one.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIRS = [REPO_ROOT / "experiments" / "runs" / "07_verdict_40claim",
                REPO_ROOT / "experiments" / "runs" / "08_verdict_59claim"]

ARM_DESC = {
    "C":  "clean retrieval only — upper bound",
    "P":  "poisoned retrieval only — **the attack baseline**",
    "PM": "poisoned retrieval merged with the model-only reasoner",
    "M":  "the same pipeline with retrieval removed entirely",
}


def pct(k, n):
    return f"{k / n:.1%}" if n else "n/a"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dirs", type=str, default=",".join(str(d) for d in DEFAULT_DIRS))
    ap.add_argument("--arms", type=str, default="C,P,PM,M")
    ap.add_argument("--stability-dir", type=str, default=str(DEFAULT_DIRS[0]),
                    help="Run dir that has a second round, used for the instability estimate.")
    args = ap.parse_args()

    dirs = [Path(d) for d in args.run_dirs.split(",")]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    rows = {}          # arm -> claim_id -> record
    origin = {}        # claim_id -> run dir name
    for d in dirs:
        for a in arms:
            p = d / f"verdicts_{a}_dropempty.json"
            if not p.exists():
                sys.exit(f"{p} not found")
            for r in json.load(open(p)):
                if r["claim_id"] in rows.setdefault(a, {}):
                    sys.exit(f"claim {r['claim_id']} appears in more than one run dir for {a}")
                rows[a][r["claim_id"]] = r
                origin[r["claim_id"]] = d.name

    cids = sorted(rows[arms[0]])
    for a in arms:
        if sorted(rows[a]) != cids:
            sys.exit(f"arm {a} covers a different claim set")

    flipped, gold = {}, {}
    for d in dirs:
        for r in json.load(open(d / "questions.json")):
            flipped[r["claim_id"]] = r["attack_flipped"]
    for c in cids:
        gold[c] = rows[arms[0]][c]["gold_label"]

    n = len(cids)
    L = [f"# Pooled verdicts — {n} claims", "",
         "Two batches (" + ", ".join(d.name for d in dirs) + ") pooled claim by claim. They "
         "share every pass, prompt, model, label and record format, so the verdicts combine "
         "directly.", "",
         "**One round per claim.** The 40-claim batch was judged twice per arm and the other "
         "once; pooling both rounds of the first would weight those claims double. Round 1 is "
         "used throughout, and the spare round is reported at the end as the instability "
         "estimate — an arm-to-arm difference means nothing unless it clears that.", "",
         "| arm | record | correct |", "|---|---|---|"]
    acc = {}
    for a in arms:
        k = sum(1 for c in cids if rows[a][c]["correct"])
        acc[a] = k
        L.append(f"| `{a}` | {ARM_DESC.get(a, '')} | **{k}/{n} = {pct(k, n)}** |")

    if "P" in acc and "C" in acc:
        L += ["", f"The attack costs **{pct(acc['C'] - acc['P'], n)}** "
                  f"({pct(acc['C'], n)} → {pct(acc['P'], n)}).", ""]

    L += ["", "## By whether run 05 saw the attack flip this claim", "",
          "`attack_flipped` is read off run 05, an independent end-to-end run. It is a "
          "stratification label, not this experiment's own measurement of whether the attack "
          "worked.", "",
          "| subset | claims | " + " | ".join(f"`{a}`" for a in arms) + " |",
          "|---" * (len(arms) + 2) + "|"]
    for want, nm in ((True, "flipped in run 05"), (False, "not flipped")):
        s = [c for c in cids if flipped.get(c) is want]
        cells = [f"{sum(1 for c in s if rows[a][c]['correct'])}/{len(s)}" for a in arms]
        L.append(f"| {nm} | {len(s)} | " + " | ".join(cells) + " |")

    L += ["", "## By gold label", "",
          "| gold | claims | " + " | ".join(f"`{a}`" for a in arms) + " |",
          "|---" * (len(arms) + 2) + "|"]
    for g in ("Refuted", "Supported"):
        s = [c for c in cids if gold[c] == g]
        cells = [f"{sum(1 for c in s if rows[a][c]['correct'])}/{len(s)}" for a in arms]
        L.append(f"| {g} | {len(s)} | " + " | ".join(cells) + " |")

    if "P" in arms and "PM" in arms:
        L += ["", "## Claim by claim, where the arms disagree", "",
              "| claim | gold | flipped | " + " | ".join(f"`{a}`" for a in arms) + " | origin |",
              "|---" * (len(arms) + 4) + "|"]
        for c in cids:
            vs = {rows[a][c]["verdict"] for a in arms}
            if len(vs) == 1:
                continue
            cells = [("✓" if rows[a][c]["correct"] else "✗") + " " + rows[a][c]["verdict"][:3]
                     for a in arms]
            L.append(f"| {c} | {gold[c]} | {'yes' if flipped.get(c) else 'no'} | "
                     + " | ".join(cells) + f" | {origin[c]} |")

    # The instability estimate. Reported as a rate, not folded into the accuracies above.
    sd = Path(args.stability_dir)
    L += ["", "## How unstable is the judge", "",
          f"Measured on {sd.name}, the batch that has a second round: the same arm, the same "
          "byte-identical record, judged twice.", "",
          "| arm | claims whose verdict changed |", "|---|---|"]
    for a in arms:
        p1, p2 = sd / f"verdicts_{a}_dropempty.json", sd / f"verdicts_{a}_dropempty_r2.json"
        if not (p1.exists() and p2.exists()):
            continue
        r1 = {r["claim_id"]: r["verdict"] for r in json.load(open(p1))}
        r2 = {r["claim_id"]: r["verdict"] for r in json.load(open(p2))}
        changed = sum(1 for c in r1 if c in r2 and r1[c] != r2[c])
        L.append(f"| `{a}` | {changed}/{len(r2)} |")

    fb = sum(1 for a in arms for c in cids if rows[a][c]["fallback_to_refuted"])
    L += ["", f"Fallback verdicts (judge produced no valid label five times running and was "
              f"silently recorded as REFUTED): **{fb}**.", ""]

    out = dirs[0] / "exp06_pooled_report.md"
    out.write_text("\n".join(L))
    print("\n".join(L[:40]))
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
