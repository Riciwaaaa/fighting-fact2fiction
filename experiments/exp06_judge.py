"""
Experiment 06, pass F -- InFact stages 5 & 6 on a record we control.

Stage 5 (Judge) reads nothing but `str(doc)`, which is "## Claim" followed by the reasoning
blocks. Stage 6 (DocSummarizer) then writes the justification from the finished document. So a
verdict can be produced from a record we assembled ourselves, with no knowledge base, no
retrieval, and no second `infact` copy involved:

    doc = FCDocument(claim=Claim(...))
    doc.add_reasoning(record)
    label = judge.judge(doc)
    doc.verdict = label
    doc.justification = doc_summarizer.summarize(doc)

The arms differ ONLY in that record (and in whether the judge is given our extra rules):

    P    poisoned retrieval alone, unanswerable questions dropped -- InFact as it actually runs,
         so this is the attack baseline
    P0   the same, but the unanswerable questions kept as rows. P and P+M otherwise differ in two
         things at once (merging, and not dropping); this arm separates them
    PM   poisoned retrieval merged with the model-only reasoner -- the thing being tested
    C    clean retrieval alone, unanswerable dropped -- upper bound
    CM   clean retrieval merged -- the false-alarm check. If merging breaks verdicts that were
         already right without it, no improvement on the poisoned side counts for anything

Previous end-to-end runs (runs/05_mimo_100claim_fusion, runs/03_mimo_27claim_binary) cannot serve
as the baseline: their clean and poisoned conditions each posed their own questions, and they used
`approach_question_batch` rather than the per-question calls of pass C. Comparing against them
would confound three differences at once. Arm P re-renders THIS experiment's own poisoned answers,
so the record is the only thing that changes.

Label space is binary (Supported/Refuted), which is where all ten claims' gold labels sit. The
four-class space would bring in two things that fight this design: AVeriTeC's built-in
argument-from-ignorance rule (`benchmark.py:112`), which is aimed at exactly the kind of decisive
absence the model-only side reports, and the CONFLICTING label, which hands the judge the
both-sides-stand escape the merged record exists to close.

Reads questions.json, answers_{clean,poisoned}.json, results_{clean,poisoned}_vs_mo.json.
Writes verdicts_<arm>.json, records_<arm>.md, judge_prompts_<arm>.md.
Run under /home/ubuntu/.venv312/bin/python3.12.
"""

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAME_DIR = REPO_ROOT / "DEFAME"
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
DEFAULT_RUN_DIR = EXPERIMENTS_DIR / "runs" / "06_symmetric_conflict"

sys.path.insert(0, str(EXPERIMENTS_DIR))
from exp06_prompts import (render_record, MERGED_RECORD_HEADER,  # noqa: E402
                           INFACT_NATIVE_HEADER, JUDGE_RULE_VARIANTS, NONE_DESCRIPTION)

# arm -> (source file, merged?, keep unanswerable rows?)
ARMS = {
    "P":  ("answers_poisoned.json", False, False),
    "P0": ("answers_poisoned.json", False, True),
    "PM": ("results_poisoned_vs_mo.json", True, True),
    "C":  ("answers_clean.json", False, False),
    "CM": ("results_clean_vs_mo.json", True, True),
    "M":  ("answers_model_only.json", False, False),
}


def build_rows(run_dir: Path, arm: str, drop_empty: bool) -> dict:
    """Rows per claim id, in the shape render_record expects."""
    fname, merged, keep_unanswerable = ARMS[arm]
    data = json.load(open(run_dir / fname))
    out = {}

    if arm == "M":
        # Retrieval removed entirely: the same 400 sub-questions, answered from memory alone.
        # This is the arm that answers "why not just drop RAG when it is poisoned?", and it is
        # the only honest way to ask it -- it shares the question set, the judge, the label
        # space and the record format with every other arm, so the sole difference from `PM` is
        # whether a document store contributed at all.
        #
        # Run 05's `model_only` column is NOT this. There the model invented its own sub-claims
        # and emitted the verdict in the same call, so comparing it against `PM` would confound
        # three differences with the one being measured. It stays an external reference point.
        for rec in data:
            rows = []
            for r in rec["rows"]:
                if r["parse_failed"] or not r.get("answer"):
                    continue        # no answer to record, as with an unanswerable question
                rows.append({"question": r["question"], "infact_url": None,
                             "infact_answer": r["answer"]})
            out[rec["claim_id"]] = rows
    elif merged:
        for r in data:
            # `by_rule` is set for exactly one combination: retrieval empty AND the reasoner has
            # no recollection. Dropping those is what makes the record match InFact's own habit
            # of deleting a question nothing could answer.
            if drop_empty and r["by_rule"]:
                continue
            out.setdefault(r["claim_id"], []).append(r)
    else:
        for rec in data:
            rows = []
            for r in rec["rows"]:
                if not r["answerable"]:
                    if not keep_unanswerable:
                        continue
                    # A bare "NONE" token is not something a judge can weigh; the sentence form
                    # is what the adjudicator was shown too.
                    rows.append({"question": r["question"], "infact_url": None,
                                 "infact_answer": NONE_DESCRIPTION})
                else:
                    rows.append({"question": r["question"], "infact_url": r["url"],
                                 "infact_answer": r["answer"]})
            out[rec["claim_id"]] = rows
    return out


def write_report(run_dir: Path, arms: list, tags: list, drop_empty: bool):
    """Aggregate every verdicts_*.json in the run dir into one report.

    Repeats are the point of this function. The judge is not deterministic -- claim 14 was
    observed returning different verdicts on a byte-identical record -- so a single round's
    one- or two-claim difference between arms carries no information. Everything below is
    reported as "correct in k of n rounds", and a claim whose verdict varies across rounds is
    marked as unstable rather than folded into an average.
    """
    suffix = "_dropempty" if drop_empty else ""
    data = {}
    for a in arms:
        for t in tags:
            p = run_dir / f"verdicts_{a}{suffix}{t}.json"
            if p.exists():
                data[(a, t)] = {r["claim_id"]: r for r in json.load(open(p))}
    present = [a for a in arms if any((a, t) in data for t in tags)]
    if not present:
        sys.exit("no verdict files found -- run the arms first")
    cids = sorted(next(iter(data.values())))
    rounds = {a: [t for t in tags if (a, t) in data] for a in present}

    L = ["# Experiment 06, pass F — verdicts from a record we control", "",
         "InFact's stages 5 (Judge) and 6 (justification) run on records assembled by us. The "
         "arms differ only in that record, and in whether the judge is given the extra rules "
         "about a two-source record. Nothing is retrieved here; the answers come from passes "
         "B, C and D.", "",
         "**The judge is not deterministic.** On a byte-identical record for claim 14 it "
         "returned different verdicts on two runs. Every arm below was therefore repeated, and "
         "a one-claim difference in a single round is not evidence of anything.", "",
         "| arm | record | judge rules |", "|---|---|---|",
         "| `C` | clean retrieval only, unanswerable questions dropped | InFact's own |",
         "| `C+M` | clean retrieval merged with the model-only reasoner | + ours |",
         "| `P` | poisoned retrieval only, unanswerable dropped — **the attack baseline** | "
         "InFact's own |",
         "| `P0` | poisoned retrieval only, unanswerable kept | InFact's own |",
         "| `P+M` | poisoned retrieval merged with the model-only reasoner | + ours |", "",
         "---", "", "## Headline", "",
         "| arm | " + " | ".join(f"round {i + 1}" for i in range(len(tags))) + " | total |",
         "|---" * (len(tags) + 2) + "|"]
    for a in present:
        ks = [sum(1 for r in data[(a, t)].values() if r["correct"]) for t in rounds[a]]
        cells = [f"{k}/{len(cids)}" for k in ks] + [""] * (len(tags) - len(ks))
        L.append(f"| `{a}` | " + " | ".join(cells) +
                 f" | **{sum(ks)}/{len(cids) * len(ks)}** |")

    L += ["", "## Per claim", "",
          "Rounds in which the verdict matched the gold label. `*` marks a claim whose verdict "
          "was not the same in every round of that arm.", "",
          "| claim | gold | attack flipped | " + " | ".join(f"`{a}`" for a in present) + " |",
          "|---" * (len(present) + 3) + "|"]
    flipped = {r["claim_id"]: r["attack_flipped"]
               for r in json.load(open(run_dir / "questions.json"))}
    for c in cids:
        cells = []
        for a in present:
            n = sum(1 for t in rounds[a] if data[(a, t)][c]["correct"])
            unstable = len({data[(a, t)][c]["verdict"] for t in rounds[a]}) > 1
            cells.append(f"{n}/{len(rounds[a])}" + ("\\*" if unstable else ""))
        L.append(f"| {c} | {data[(present[0], rounds[present[0]][0])][c]['gold_label']} | "
                 f"{'yes' if flipped[c] else 'no'} | " + " | ".join(cells) + " |")

    if "P" in present and "PM" in present:
        L += ["", "## What merging changed on the poisoned side", "",
              "Counted per claim over the rounds both arms have.", "",
              "| claim | `P` | `P+M` | |", "|---|---|---|---|"]
        n_r = min(len(rounds["P"]), len(rounds["PM"]))
        for c in cids:
            p = sum(1 for t in rounds["P"][:n_r] if data[("P", t)][c]["correct"])
            m = sum(1 for t in rounds["PM"][:n_r] if data[("PM", t)][c]["correct"])
            if p != m:
                L.append(f"| {c} | {p}/{n_r} | {m}/{n_r} | "
                         f"{'recovered' if m > p else '**lost**'} |")

    fb = [(a, t, c) for (a, t), rows in data.items()
          for c, r in rows.items() if r["fallback_to_refuted"]]
    L += ["", "## Fallback verdicts", "",
          "Under the binary label space the judge retries five times and then silently falls "
          "back to REFUTED (`judge.py:50`), which would look like a confident refutation.", "",
          f"Occurrences: **{len(fb)}**" + (f" — {fb}" if fb else "."), ""]

    L += ["", "---", "", "## Judge reasoning, claim by claim", "",
          "The first round of each arm.", ""]
    for c in cids:
        L += [f"### Claim {c} — {data[(present[0], rounds[present[0]][0])][c]['claim']}", ""]
        for a in present:
            r = data[(a, rounds[a][0])][c]
            L += [f"**`{a}` → `{r['verdict']}`** ({'matches gold' if r['correct'] else 'wrong'}, "
                  f"{r['n_entries']} entries)", "", r["judge_reasoning"] or "*(none)*", ""]
        L += ["---", ""]

    out = run_dir / "exp06_verdict_report.md"
    out.write_text("\n".join(L))
    print(f"report -> {out}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=str, default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--arms", type=str, default="P,P0,PM,C,CM")
    parser.add_argument("--claims", type=str, default=None)
    parser.add_argument("--drop-empty", action="store_true",
                        help="Merged arms only: delete questions neither side could answer, "
                             "the way InFact's own procedure deletes unanswerable ones.")
    parser.add_argument("--fc-model", type=str, default="mimo_v25_pro")
    # Two LLM calls per claim (verdict, then justification) and no local compute,
    # so this is bounded by the API rather than by the box.
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--tag", type=str, default="",
                        help="Appended to the output filenames. Use it to run an arm more than "
                             "once: the judge is not deterministic, and claim 14 was observed "
                             "returning different verdicts on a byte-identical record, so a "
                             "one- or two-claim difference between arms means nothing until the "
                             "same arm has been repeated.")
    parser.add_argument("--report-only", action="store_true",
                        help="Skip the LLM entirely; aggregate the verdict files already on "
                             "disk into exp06_verdict_report.md.")
    parser.add_argument("--report-tags", type=str, default=",_r2,_r3",
                        help="Comma-separated --tag values to aggregate (empty string = the "
                             "untagged first round).")
    parser.add_argument("--judge-rules", choices=sorted(JUDGE_RULE_VARIANTS), default="v2",
                        help="Which extra rules the merged arms' judge is given. v2 is the "
                             "current design; v1 reproduces the condition that produced "
                             "runs/14_binary100_pr008 and exists for the ablation. The baseline "
                             "arms (C, P, P0, M) get no extra rules under either.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()      # resolve before chdir
    questions = {r["claim_id"]: r for r in json.load(open(run_dir / "questions.json"))}
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    for a in arms:
        if a not in ARMS:
            sys.exit(f"unknown arm {a!r}; choose from {sorted(ARMS)}")

    if args.report_only:
        write_report(run_dir, arms, args.report_tags.split(","), args.drop_empty)
        return

    rows_by_arm = {a: build_rows(run_dir, a, args.drop_empty) for a in arms}

    want = ({int(x) for x in args.claims.split(",")} if args.claims else None)
    cids = sorted(questions if want is None else want)

    # cwd must be DEFAME: prompt templates and config/api_keys.yaml resolve relative to it.
    os.chdir(DEFAME_DIR)
    sys.path.insert(0, str(DEFAME_DIR))
    from infact.common.content import Content
    from infact.common.claim import Claim
    from infact.common.document import FCDocument
    from infact.common.label import Label
    from infact.common.logger import Logger
    from infact.common.modeling import make_model
    from infact.eval.benchmark import AVeriTeC
    from infact.modules.judge import Judge
    from infact.modules.doc_summarizer import DocSummarizer
    from infact.prompts.prompt import JudgePrompt

    classes = [Label.SUPPORTED, Label.REFUTED]
    class_definitions = {c: AVeriTeC.class_definitions[c] for c in classes}

    logger = Logger(print_log_level="warning")
    llm = make_model(args.fc_model, logger=logger)
    summarizer = DocSummarizer(llm, logger)

    suffix = ("_dropempty" if args.drop_empty else "") + args.tag

    for arm in arms:
        _, merged, _ = ARMS[arm]
        header = MERGED_RECORD_HEADER if merged else INFACT_NATIVE_HEADER
        # The baseline arms get InFact's judge exactly as it ships. A baseline that has been
        # handed our rules is not a baseline.
        extra_rules = JUDGE_RULE_VARIANTS[args.judge_rules] if merged else None

        results, t0 = {}, time.perf_counter()
        write_lock = threading.Lock()

        def judge_claim(cid, _arm=arm, _header=header, _merged=merged,
                        _extra_rules=extra_rules, _suffix=suffix):
            rows = rows_by_arm[_arm][cid]
            claim_text = questions[cid]["claim"]
            record = render_record(rows, header=_header, mark_conflicts=_merged)

            content = Content(text=claim_text)
            doc = FCDocument(claim=Claim(text=claim_text, original_context=content))
            doc.add_reasoning(record)

            prompt = str(JudgePrompt(doc, classes, class_definitions, _extra_rules))
            # One Judge per claim, not one shared across the arm. Judge stashes the model's raw
            # response on itself (`latest_reasoning`) and get_latest_reasoning() reads it back,
            # so a shared instance run from several threads would hand one claim another
            # claim's reasoning. Construction is cheap -- it just wraps the existing llm.
            judge = Judge(llm=llm, logger=logger, classes=classes,
                          class_definitions=class_definitions, extra_rules=_extra_rules)
            verdict = judge.judge(doc)
            reasoning = judge.get_latest_reasoning()

            # Judge._get_verdict retries five times and then silently falls back to REFUTED
            # (judge.py:50), which would show up as a confident refutation. Re-extract from the
            # reasoning it actually produced to tell the two apart.
            fallback = (verdict == Label.REFUTED
                        and judge.extract_verdict(reasoning or "") == Label.REFUSED_TO_ANSWER)

            doc.verdict = verdict
            doc.justification = summarizer.summarize(doc)

            gold = questions[cid]["gold_label"]
            correct = verdict.value == str(gold).lower()
            rec = {"arm": _arm, "drop_empty": args.drop_empty, "claim_id": cid,
                   "claim": claim_text, "gold_label": gold,
                   "verdict": verdict.value, "correct": correct,
                   "fallback_to_refuted": fallback,
                   "n_entries": len(rows),
                   "justification": doc.justification,
                   "judge_reasoning": reasoning}

            with write_lock:
                results[cid] = (rec, f"# Claim {cid} — {claim_text}\n\n{record}",
                                f"# Claim {cid}\n\n```\n{prompt}\n```")
                print(f"[{_arm}{_suffix} {cid}] {len(rows)} entries | gold {gold} -> "
                      f"{verdict.value}{' (FALLBACK)' if fallback else ''} "
                      f"{'OK' if correct else 'WRONG'}", flush=True)
                # Written on every completion, as the serial version did: a run that dies
                # partway (credits, a kill) leaves the claims it finished rather than nothing.
                with open(run_dir / f"verdicts_{_arm}{_suffix}.json", "w") as f:
                    json.dump([results[c][0] for c in sorted(results)], f, indent=2)

        # A claim absent from this arm's source is NOT a claim with an empty record. Arms P and
        # P+M only exist where Fact2Fiction actually attacked; feeding the judge an empty record
        # for the rest makes it invent a verdict from the claim text alone (it says so outright
        # -- "the Record section does not contain any actual evidence" -- and then rules anyway),
        # and downstream that looks like a real verdict, so the P<-C / P+M<-CM backfill never
        # fires. Judge only what this arm has; exp08_final_report.py fills the rest in.
        arm_cids = [c for c in cids if c in rows_by_arm[arm]]
        skipped = len(cids) - len(arm_cids)
        if skipped:
            print(f"{arm}{suffix}: {skipped} of {len(cids)} claims have no record for this arm "
                  f"and are left out (they get backfilled from the unpoisoned arm)", flush=True)

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            list(ex.map(judge_claim, arm_cids))

        out = [results[c][0] for c in sorted(results)]
        records = [results[c][1] for c in sorted(results)]
        prompts = [results[c][2] for c in sorted(results)]

        (run_dir / f"records_{arm}{suffix}.md").write_text("\n\n".join(records))
        (run_dir / f"judge_prompts_{arm}{suffix}.md").write_text("\n\n".join(prompts))
        k = sum(1 for r in out if r["correct"])
        fb = sum(1 for r in out if r["fallback_to_refuted"])
        print(f"{arm}{suffix}: {k}/{len(out)} match gold"
              + (f" | {fb} fell back to REFUTED" if fb else "")
              + f" ({time.perf_counter() - t0:.0f}s)\n", flush=True)


if __name__ == "__main__":
    main()
