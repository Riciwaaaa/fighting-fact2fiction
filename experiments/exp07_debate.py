"""
Experiment 07 -- debate over InFact's finished verdict.

InFact runs untouched; its verdict V is then argued over. Because the label space is binary, the
opposing position is fixed by V and nothing has to be chosen: the defender argues V from the
retrieved record, the challenger argues the other label from memory alone, and a judge that never
sees the record picks one.

Arms, all over the same 99 claims:

    DBT-P       debate over the poisoned verdict            -- the experiment
    DBT-C       debate over the clean verdict               -- the false-alarm check. Where the
                attack never landed, `P` is already right most of the time, so debate has only
                downside there; answer reversal is the first failure mode reported for
                multi-agent debate and this is where it would show
    CSL-P       challenger speaks, defender does not        -- isolates adversarial structure
                from "a second voice was added". Khan et al. find a lone advocate makes the
                judge WORSE while an adversarial pair makes it better; without this arm the two
                are indistinguishable
    NAIVE-P     nobody speaks                               -- measures what the judge loses by
                being blind to the record, which is a cost of the design, not of debate
    DBT-P-swap  debate, challenger opens                    -- position bias control

Reads the pass F outputs of runs 07 and 08 (verdicts_{P,C}_dropempty.json) and rebuilds each
claim's record with the same function the verdict stage used, so the defender reads exactly what
InFact's judge read. Writes debate_<arm>.json and debate_<arm>.md.

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
from fusion_common import call_json, set_model, _call_resilient  # noqa: E402
from exp06_prompts import render_record, INFACT_NATIVE_HEADER  # noqa: E402
from exp06_judge import build_rows  # noqa: E402
from exp07_prompts import (DEFENDER_PROMPT, CHALLENGER_PROMPT,  # noqa: E402
                           DEBATE_JUDGE_PROMPT, WORD_LIMIT, verify_quotes, valid_judge)

LABELS = ("supported", "refuted")

# arm -> (verdict to argue over, defender speaks?, challenger speaks?, challenger opens?)
ARMS = {
    "DBT-P":      ("P", True,  True,  False),
    "DBT-C":      ("C", True,  True,  False),
    "CSL-P":      ("P", False, True,  True),
    "NAIVE-P":    ("P", False, False, False),
    "DBT-P-swap": ("P", True,  True,  True),
}


def counter_of(verdict: str) -> str:
    other = [x for x in LABELS if x != verdict.lower()]
    if len(other) != 1:
        raise ValueError(f"verdict {verdict!r} is not one of {LABELS}")
    return other[0]


def load_all(dirs, arm_letter):
    """Verdicts and rendered records for every claim across the run dirs."""
    verdicts, records = {}, {}
    for d in dirs:
        rows_by_claim = build_rows(d, arm_letter, drop_empty=True)
        for r in json.load(open(d / f"verdicts_{arm_letter}_dropempty.json")):
            cid = r["claim_id"]
            if cid in verdicts:
                sys.exit(f"claim {cid} appears in more than one run dir")
            verdicts[cid] = r
            records[cid] = render_record(rows_by_claim.get(cid, []),
                                         header=INFACT_NATIVE_HEADER, mark_conflicts=False)
    return verdicts, records


def speak(prompt: str) -> str:
    """One debater turn. Plain text, not JSON -- an argument is prose."""
    r = _call_resilient(prompt)
    if r is None:
        return ""
    return (getattr(r, "content", None) or str(r)).strip()


def run_claim(rec, record, arm, rounds):
    """Hold one debate and return the transcript plus the judge's verdict."""
    _, defends, challenges, challenger_opens = ARMS[arm]
    claim, verdict = rec["claim"], rec["verdict"].lower()
    counter = counter_of(verdict)

    transcript = []
    counts = {"ok": 0, "bad": 0}

    def render_transcript():
        return ("\n\n".join(transcript) if transcript
                else "(nothing has been said yet; this is the opening statement)")

    def defender_turn():
        text = speak(DEFENDER_PROMPT
                     .replace("[WORD_LIMIT]", str(WORD_LIMIT))
                     .replace("[CLAIM]", claim)
                     .replace("[VERDICT]", verdict)
                     .replace("[RECORD]", record)
                     .replace("[TRANSCRIPT]", render_transcript()))
        # Quotes are checked before the text enters the transcript, so the challenger and the
        # judge only ever see them already tagged.
        text, ok, bad = verify_quotes(text, record)
        counts["ok"] += ok
        counts["bad"] += bad
        transcript.append(f"**Debater arguing `{verdict}` (has the documents):**\n{text}")

    def challenger_turn():
        text = speak(CHALLENGER_PROMPT
                     .replace("[WORD_LIMIT]", str(WORD_LIMIT))
                     .replace("[CLAIM]", claim)
                     .replace("[VERDICT]", verdict)
                     .replace("[COUNTER_VERDICT]", counter)
                     .replace("[TRANSCRIPT]", render_transcript()))
        transcript.append(f"**Debater arguing `{counter}` (no documents):**\n{text}")

    order = ([("c", challenger_turn), ("d", defender_turn)] if challenger_opens
             else [("d", defender_turn), ("c", challenger_turn)])
    for _ in range(rounds):
        for who, turn in order:
            if (who == "d" and defends) or (who == "c" and challenges):
                turn()

    body = (render_transcript() if transcript else
            "(no debate was held; decide from the Claim and the two verdicts alone)")

    adj = call_json(DEBATE_JUDGE_PROMPT
                    .replace("[CLAIM]", claim)
                    .replace("[VERDICT]", verdict)
                    .replace("[COUNTER_VERDICT]", counter)
                    .replace("[TRANSCRIPT]", body),
                    lambda d: valid_judge(d, verdict, counter))
    final = ((adj or {}).get("verdict") or "").strip().strip("`").lower() or None

    return {
        "claim_id": rec["claim_id"],
        "arm": arm,
        "claim": claim,
        "gold_label": rec["gold_label"],
        "start_verdict": verdict,
        "counter_verdict": counter,
        "start_correct": rec["correct"],
        "debate_verdict": final,
        "correct": (final == str(rec["gold_label"]).lower()) if final else None,
        "changed": (final != verdict) if final else None,
        "judge_reason": (adj or {}).get("reason"),
        "judge_failed": final is None,
        "quotes_verified": counts["ok"],
        "quotes_unverified": counts["bad"],
        "transcript": transcript,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dirs", type=str, default=",".join(str(d) for d in DEFAULT_DIRS))
    ap.add_argument("--arms", type=str, default="DBT-P,DBT-C,CSL-P,NAIVE-P,DBT-P-swap")
    ap.add_argument("--claims", type=str, default=None)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--model", type=str, default="xiaomi/mimo-v2.5-pro")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out-dir", type=str, default=str(DEFAULT_DIRS[0]))
    args = ap.parse_args()

    set_model(args.model)
    dirs = [Path(d) for d in args.run_dirs.split(",")]
    out_dir = Path(args.out_dir).resolve()
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    for a in arms:
        if a not in ARMS:
            sys.exit(f"unknown arm {a!r}; choose from {sorted(ARMS)}")

    cache = {}
    for a in arms:
        letter = ARMS[a][0]
        if letter not in cache:
            cache[letter] = load_all(dirs, letter)

    want = ({int(x) for x in args.claims.split(",")} if args.claims else None)

    for arm in arms:
        verdicts, records = cache[ARMS[arm][0]]
        cids = sorted(c for c in verdicts if want is None or c in want)
        t0 = time.perf_counter()

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            out = list(ex.map(lambda c: run_claim(verdicts[c], records[c], arm, args.rounds),
                              cids))

        for r in out:
            flag = ("judge FAILED" if r["judge_failed"] else
                    ("changed" if r["changed"] else "held"))
            print(f"[{arm} {r['claim_id']}] {r['start_verdict']} -> {r['debate_verdict']} "
                  f"({flag}) | gold {r['gold_label']} "
                  f"{'OK' if r['correct'] else 'WRONG'}"
                  + (f" | quotes {r['quotes_verified']}v/{r['quotes_unverified']}u"
                     if r["quotes_verified"] or r["quotes_unverified"] else ""), flush=True)

        k = sum(1 for r in out if r["correct"])
        k0 = sum(1 for r in out if r["start_correct"])
        fixed = sum(1 for r in out if r["correct"] and not r["start_correct"])
        broke = sum(1 for r in out if r["start_correct"] and r["correct"] is False)
        bad = sum(1 for r in out if r["judge_failed"])
        print(f"\n{arm}: {k}/{len(out)} correct (started at {k0}/{len(out)}) "
              f"| fixed {fixed}, broke {broke}"
              + (f" | JUDGE FAILED {bad}" if bad else "")
              + f" ({time.perf_counter() - t0:.0f}s)\n", flush=True)

        with open(out_dir / f"debate_{arm}.json", "w") as f:
            json.dump(out, f, indent=2)
        (out_dir / f"debate_{arm}.md").write_text("\n\n".join(
            f"# Claim {r['claim_id']} — {r['claim']}\n\n"
            f"gold `{r['gold_label']}` · InFact `{r['start_verdict']}` · "
            f"after debate `{r['debate_verdict']}`\n\n"
            + "\n\n".join(r["transcript"])
            + f"\n\n**Judge:** {r['judge_reason']}" for r in out))


if __name__ == "__main__":
    main()
