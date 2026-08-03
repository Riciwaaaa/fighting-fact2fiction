"""
Experiment 06, pass E -- adjudicate, merge, and report.

Produces TWO result tables over the same 100 questions:

    clean InFact    vs model-only
    poisoned InFact vs model-only

The two InFact conditions are never compared to each other. Every question appears in both
tables; nothing is dropped for being unanswerable.

Exactly ONE combination is settled without the LLM:

    InFact NONE   + model-only no_recollection  -> agree     both empty-handed, nothing to judge
    everything else                             -> LLM adjudicates

An earlier draft also ruled the two asymmetric cases (one side empty, the other not) as automatic
conflicts. The claim-4 smoke run showed why that is wrong: both knowledge bases answered all ten
questions, so the four `no_recollection` rows fired the rule identically on both sides, adding the
same four conflicts to each and diluting the only quantity the experiment is trying to measure.
"The reasoner does not know this" carries no information about whether the corpus was poisoned;
whether it *conflicts* with what retrieval said is a judgement, so the LLM makes it.

When retrieval came up empty the adjudicator is shown `NONE_DESCRIPTION` rather than the bare
sentinel, because a retrieval failure is itself a substantive report about the corpus and the
judge has to be able to read it as one.

Each row records `by_rule` so the (now small) rule-resolved population can be reported separately.

The same call also MERGES the two answers into one record entry. Every question therefore leaves
this pass as a single `merged` paragraph: one combined finding where the two sides agree, both
positions side by side and unresolved where they conflict. Those entries are rendered per claim
into the record shape InFact's own procedure builds, ready for the verdict stage to read. That
stage is not run here.

Merging shares the adjudication call because it needs the disagreement already located, which is
what adjudication produces. The model-only confidence enters here and nowhere else: the record
format has no field for a number, so the only way the score survives into the verdict stage is as
prose. The prompt is given the number and forbidden from copying it into the text -- a bare score
means nothing without its scale, and the retrieval side has no counterpart score to compare it
with, since InFact scores no evidence at all.

Reads answers_{clean,poisoned,model_only}.json. Writes results_clean_vs_mo.json,
results_poisoned_vs_mo.json, merged_records_{clean,poisoned}.{json,md} and exp06_report.md.
"""

import argparse
import json
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
DEFAULT_RUN_DIR = EXPERIMENTS_DIR / "runs" / "06_symmetric_conflict"

sys.path.insert(0, str(EXPERIMENTS_DIR))
from fusion_common import call_json, set_model  # noqa: E402
from exp06_prompts import (ADJUDICATE_MERGE_PROMPT, NONE_DESCRIPTION,  # noqa: E402
                           BASES, valid_adj, NO_CONFIDENCE, render_record,
                           MERGED_BOTH_EMPTY, MERGED_MO_FAILED)

# Ways a score could leak into the merged prose despite the prompt forbidding it. Checked on
# every row rather than trusted, because the merged text is the one artefact that leaves this
# pass, and a number in it would reach the verdict stage with no scale attached.
SCORE_LEAK = re.compile(r"\b\d{1,3}\s*(?:/|out of)\s*100\b|\bconfiden\w*\s*(?:of|:|=)?\s*\d"
                        r"|\bscored?\s+\d|\b\d{1,3}\s*%\s*(?:confiden|sure|certain)", re.I)


def rule_label(infact_answerable: bool, mo_basis: str):
    """The one combination settled without the LLM, else None. See module docstring."""
    if not infact_answerable and mo_basis == "no_recollection":
        return ("agree", "retrieval found nothing and model-only has no recollection either "
                "-- both empty-handed, nothing to compare")
    return None


def pct(k, n):
    return f"{k / n:.1%}" if n else "n/a"


def rate_rows(rows):
    n = len(rows)
    k = sum(1 for r in rows if r["relation"] == "conflict")
    return n, k, (k / n if n else float("nan"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=str, default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--model", type=str, default="xiaomi/mimo-v2.5-pro")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--sides", type=str, default="clean,poisoned",
                        help="Which tables to (re)build. Restricting this re-uses the existing "
                             "results file for the other side, which is what you want after a "
                             "run died partway -- the surviving side cost real money.")
    parser.add_argument("--expect", type=int, default=100,
                        help="Expected rows per table; 0 disables the check")
    args = parser.parse_args()

    set_model(args.model)
    run_dir = Path(args.run_dir).resolve()

    def load(name):
        p = run_dir / f"answers_{name}.json"
        if not p.exists():
            sys.exit(f"{p} not found -- run the earlier passes first")
        return {r["claim_id"]: r for r in json.load(open(p))}

    clean, poisoned, mo = load("clean"), load("poisoned"), load("model_only")
    cids = sorted(set(clean) & set(poisoned) & set(mo))
    missing = (set(clean) | set(poisoned) | set(mo)) - set(cids)
    if missing:
        print(f"WARNING: claims present in only some passes, excluded: {sorted(missing)}")

    want_sides = [s.strip() for s in args.sides.split(",") if s.strip()]
    tables = {}
    for side, data in (("clean", clean), ("poisoned", poisoned)):
        if side not in want_sides:
            # Not rebuilding this side: load what a previous run left behind, so the report
            # below still has both tables to compare.
            p = run_dir / f"results_{side}_vs_mo.json"
            if not p.exists():
                sys.exit(f"--sides excludes {side} but {p} does not exist")
            tables[side] = json.load(open(p))
            print(f"{side}: reusing {len(tables[side])} rows from {p.name}", flush=True)
            continue
        t0 = time.perf_counter()
        jobs, rows = [], []

        for cid in cids:
            infact_rows = {r["question"]: r for r in data[cid]["rows"]}
            for m in mo[cid]["rows"]:
                q = m["question"]
                inf = infact_rows.get(q)
                if inf is None:
                    sys.exit(f"[{cid}] question missing from the {side} answers: {q!r}. "
                             "The three passes must share one question set.")
                row = {
                    "claim_id": cid,
                    "attack_flipped": mo[cid]["attack_flipped"],
                    "question": q,
                    "infact_answer": inf["answer"],
                    "infact_answerable": inf["answerable"],
                    "infact_url": inf.get("url"),
                    "is_fake": inf.get("is_fake"),          # analysis only
                    "mo_answer": m["answer"],
                    "mo_basis": m["answer_basis"],
                    "mo_premise": m["premise_status"],
                    "mo_confidence": m["confidence"],
                    "mo_parse_failed": m["parse_failed"],
                }
                ruled = (None if m["parse_failed"]
                         else rule_label(inf["answerable"], m["answer_basis"]))
                if ruled:
                    row.update(relation=ruled[0], relation_reason=ruled[1], by_rule=True,
                               merged=MERGED_BOTH_EMPTY)
                elif m["parse_failed"]:
                    # No relation to judge, but the question still needs a record entry, so the
                    # one side that did answer goes in on its own.
                    row.update(relation=None, relation_reason=None, by_rule=False,
                               merged=MERGED_MO_FAILED.format(
                                   infact_answer=(row["infact_answer"] if inf["answerable"]
                                                  else NONE_DESCRIPTION)))
                else:
                    row.update(relation=None, relation_reason=None, by_rule=False, merged=None)
                    jobs.append(row)
                rows.append(row)

        def adjudicate(row):
            # A retrieval failure reaches the judge as a sentence it can weigh, not as the
            # bare "NONE" token the answer file stores.
            infact_answer = (row["infact_answer"] if row["infact_answerable"]
                             else NONE_DESCRIPTION)
            conf = row["mo_confidence"]
            return call_json(
                ADJUDICATE_MERGE_PROMPT
                .replace("[CLAIM]", mo[row["claim_id"]]["claim"])
                .replace("[QUESTION]", row["question"])
                .replace("[INFACT_ANSWER]", infact_answer)
                .replace("[MO_ANSWER]", row["mo_answer"])
                .replace("[MO_CONFIDENCE]",
                         str(conf) if isinstance(conf, (int, float)) else NO_CONFIDENCE),
                valid_adj)

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            for row, adj in zip(jobs, ex.map(adjudicate, jobs)):
                row["relation"] = (adj or {}).get("relation")
                row["relation_reason"] = (adj or {}).get("reason")
                row["merged"] = (adj or {}).get("merged")

        # A short table means something was silently dropped -- the exact bug this
        # experiment was rebuilt to remove. Fail rather than report a plausible number.
        if args.expect and len(rows) != args.expect:
            sys.exit(f"FATAL: {side} table has {len(rows)} rows, expected {args.expect}.")

        n, k, r = rate_rows([x for x in rows if x["relation"]])
        leaks = [x for x in rows if x["merged"] and SCORE_LEAK.search(x["merged"])]
        no_merge = [x for x in rows if not x["merged"]]
        print(f"{side}: {len(rows)} rows | {len(jobs)} LLM-adjudicated, "
              f"{len(rows) - len(jobs)} templated | conflict {k}/{n} = {pct(k, n)} "
              f"| merged {len(rows) - len(no_merge)}/{len(rows)}"
              + (f" | SCORE LEAKED into {len(leaks)} merged entries" if leaks else "")
              + f" ({time.perf_counter() - t0:.0f}s)", flush=True)
        for x in leaks:
            print(f"  leak [{x['claim_id']}] {x['merged'][:160]}", file=sys.stderr)
        tables[side] = rows
        with open(run_dir / f"results_{side}_vs_mo.json", "w") as f:
            json.dump(rows, f, indent=2)

        # The merged record, per claim, in the shape the verdict stage reads. Rows whose merge
        # failed are dropped from the record -- a record entry with a hole in it is worse than
        # one question fewer -- but they stay in the results table and are counted above.
        records = {}
        for cid in cids:
            cr = [x for x in rows if x["claim_id"] == cid and x["merged"]]
            records[str(cid)] = {"claim": mo[cid]["claim"],
                                 "claim_date": mo[cid]["claim_date"],
                                 "n_entries": len(cr),
                                 "n_conflicts": sum(1 for x in cr if x["relation"] == "conflict"),
                                 "record": render_record(cr)}
        with open(run_dir / f"merged_records_{side}.json", "w") as f:
            json.dump(records, f, indent=2)
        (run_dir / f"merged_records_{side}.md").write_text(
            "\n\n".join(f"# Claim {cid} — {records[str(cid)]['claim']}\n\n"
                        f"{records[str(cid)]['record']}" for cid in cids))

    # ---------------------------------------------------------------- report
    labelled = {s: [r for r in t if r["relation"]] for s, t in tables.items()}
    n_c, k_c, r_c = rate_rows(labelled["clean"])
    n_p, k_p, r_p = rate_rows(labelled["poisoned"])

    L = ["# Experiment 06 — symmetric three-way sub-question conflict", "",
         "One shared question set, posed once by InFact stages 1&2 and answered by three "
         "systems: InFact stages 3&4 on the **clean** knowledge base, the same stages on the "
         "**poisoned** knowledge base, and a retrieval-free **model-only** reasoner.", "",
         "**Nothing is dropped.** A question InFact could not answer is recorded as a `NONE` row "
         "rather than deleted, so both tables cover the identical question set. Earlier probes "
         "measured only the questions retrieval had already succeeded on, which excluded exactly "
         "the cases of interest.", "",
         f"Sample: **{len(cids)} claims**, {len(tables['clean'])} questions, "
         f"{3 * len(tables['clean'])} answers.", "",
         "---", "", "## Headline", "",
         "| comparison | rows | conflicts | **conflict rate** |", "|---|---|---|---|",
         f"| clean InFact vs model-only | {n_c} | {k_c} | **{pct(k_c, n_c)}** |",
         f"| poisoned InFact vs model-only | {n_p} | {k_p} | **{pct(k_p, n_p)}** |", ""]
    if n_c and n_p and r_c:
        L += [f"**Poisoned minus clean: {r_p - r_c:+.1%}** ({r_p:.1%} vs {r_c:.1%}), "
              f"ratio **{r_p / r_c:.1f}×**.", ""]

    L += ["### Rule-resolved vs LLM-resolved", "",
          "Rule-resolved rows are the structural pairings (one side empty-handed). A headline "
          "driven mostly by these means something different from one driven by semantic "
          "disagreement.", "",
          "| comparison | by rule | conflict rate (rule) | by LLM | conflict rate (LLM) |",
          "|---|---|---|---|---|"]
    for side in ("clean", "poisoned"):
        rr = [r for r in labelled[side] if r["by_rule"]]
        lr = [r for r in labelled[side] if not r["by_rule"]]
        n1, k1, _ = rate_rows(rr)
        n2, k2, _ = rate_rows(lr)
        L.append(f"| {side} | {n1} | {pct(k1, n1)} | {n2} | {pct(k2, n2)} |")

    L += ["", "### Answerability", "",
          "How often each knowledge base could answer at all. A question the poisoned KB answers "
          "but the clean KB cannot is planted evidence manufacturing answerability.", "",
          "| knowledge base | answered | NONE |", "|---|---|---|"]
    for side in ("clean", "poisoned"):
        t = tables[side]
        a = sum(1 for r in t if r["infact_answerable"])
        L.append(f"| {side} | {a}/{len(t)} ({pct(a, len(t))}) | {len(t) - a} |")
    both = sum(1 for c, p in zip(tables["clean"], tables["poisoned"])
               if p["infact_answerable"] and not c["infact_answerable"])
    L += ["", f"Answerable by the poisoned KB but **not** by the clean KB: **{both}**.", ""]

    L += ["### Poisoned side: planted vs authentic evidence", "",
          "`is_fake` is derived from the source URL and is withheld from every prompt.", "",
          "| evidence | rows | conflicts | conflict rate |", "|---|---|---|---|"]
    for nm, sel in (("planted", lambda r: r["is_fake"]),
                    ("authentic", lambda r: r["infact_answerable"] and not r["is_fake"]),
                    ("NONE (unanswerable)", lambda r: not r["infact_answerable"])):
        s = [r for r in labelled["poisoned"] if sel(r)]
        n, k, _ = rate_rows(s)
        L.append(f"| {nm} | {n} | {k} | **{pct(k, n)}** |")

    L += ["", "### Conflict rate by the model-only answer's basis", "",
          "**A falsifiable check on `answer_basis` itself:** if the three levels do not separate, "
          "the model is confabulating its own basis and the field should be dropped.", "",
          "| basis | side | rows | conflicts | conflict rate |", "|---|---|---|---|---|"]
    for b in BASES:
        for side in ("clean", "poisoned"):
            s = [r for r in labelled[side] if r["mo_basis"] == b]
            n, k, _ = rate_rows(s)
            L.append(f"| `{b}` | {side} | {n} | {k} | **{pct(k, n)}** |")

    # Are the scores spread out, or piled onto a few round numbers? Vanilla verbalized
    # confidence is known to pile onto multiples of five in the 80-100 band (Xiong et al.,
    # appendix B.3), so this is the check that the Self-Probing call is doing better.
    allc = sorted(r["mo_confidence"] for r in tables["poisoned"]
                  if isinstance(r["mo_confidence"], (int, float)))
    if allc:
        buckets = Counter(min(int(c / 10), 9) for c in allc)
        L += ["", "### Confidence distribution", "",
              "Checking the scale is used rather than a few round numbers.", "",
              "| bucket | rows |", "|---|---|"]
        for b in range(10):
            if buckets[b]:
                L.append(f"| {b * 10}-{b * 10 + 9} | {buckets[b]} |")
        L += ["", f"distinct values: {len(set(allc))}, "
                  f"mean {sum(allc) / len(allc):.1f}", ""]

    L += ["", "### By whether the attack flipped that claim's verdict", "",
          "Stratification only — this experiment computes no verdict.", "",
          "| subset | vs clean | vs poisoned |", "|---|---|---|"]
    for nm, want in (("attack flipped", True), ("attack did not flip", False)):
        cells = []
        for side in ("clean", "poisoned"):
            s = [r for r in labelled[side] if r["attack_flipped"] is want]
            n, k, _ = rate_rows(s)
            cells.append(f"{k}/{n} = {pct(k, n)}")
        L.append(f"| {nm} | " + " | ".join(cells) + " |")

    L += ["", "---", "", "## Per claim", "",
          "| claim | gold | flipped | clean answered | poisoned answered | planted | "
          "vs clean | vs poisoned |", "|---|---|---|---|---|---|---|---|"]
    for cid in cids:
        cells = []
        for side in ("clean", "poisoned"):
            s = [r for r in labelled[side] if r["claim_id"] == cid]
            n, k, _ = rate_rows(s)
            cells.append(f"{k}/{n} ({pct(k, n)})")
        ca = sum(1 for r in tables["clean"] if r["claim_id"] == cid and r["infact_answerable"])
        pa = sum(1 for r in tables["poisoned"] if r["claim_id"] == cid and r["infact_answerable"])
        pf = sum(1 for r in tables["poisoned"] if r["claim_id"] == cid and r["is_fake"])
        L.append(f"| {cid} | {mo[cid]['gold_label']} | "
                 f"{'yes' if mo[cid]['attack_flipped'] else 'no'} | {ca}/10 | {pa}/10 | {pf} | "
                 + " | ".join(cells) + " |")

    bad = sum(1 for t in tables.values() for r in t if r["mo_parse_failed"])
    if bad:
        L += ["", f"**{bad} rows have an unparseable model-only answer** and carry no relation; "
                  "they are in the tables but excluded from every rate above.", ""]

    # ---------------------------------------------------------------- merged records
    L += ["", "---", "", "## Merged records", "",
          "Each question leaves this pass as one record entry: a combined finding where the two "
          "sides agree, both positions side by side and unresolved where they conflict. The "
          "model-only confidence is carried in as wording, because the record format the verdict "
          "stage reads has no field for a number.", "",
          "| side | entries | conflicts marked | not merged |", "|---|---|---|---|"]
    for side in ("clean", "poisoned"):
        t = tables[side]
        merged = [r for r in t if r["merged"]]
        L.append(f"| {side} | {len(merged)}/{len(t)} | "
                 f"{sum(1 for r in merged if r['relation'] == 'conflict')} | "
                 f"{len(t) - len(merged)} |")

    def conf_of(r):
        c = r["mo_confidence"]
        return c if isinstance(c, (int, float)) else -1

    L += ["", "### Samples", "",
          "Three entries from the poisoned side: one agreement, and the two conflicts where the "
          "model-only side was most and least sure of itself.", ""]
    pm = [r for r in tables["poisoned"] if r["merged"] and not r["by_rule"]]
    confl = sorted([r for r in pm if r["relation"] == "conflict"], key=conf_of)
    picks = []
    if confl:
        picks.append(("conflict, model-only most sure", confl[-1]))
        picks.append(("conflict, model-only least sure", confl[0]))
    agr = [r for r in pm if r["relation"] == "agree"]
    if agr:
        picks.append(("agreement", agr[0]))
    for nm, r in picks:
        L += [f"**{nm}** — claim {r['claim_id']}, model-only confidence {r['mo_confidence']}",
              "", f"*Q:* {r['question']}", "",
              f"*InFact (poisoned):* {r['infact_answer']}", "",
              f"*model-only:* {r['mo_answer']}", "",
              f"*merged:* {r['merged']}", "", "---", ""]

    L += ["", "---", "", "## Every row", ""]
    for side in ("clean", "poisoned"):
        L += [f"### {side} InFact vs model-only", ""]
        for r in tables[side]:
            tag = ("planted" if r["is_fake"] else
                   "NONE" if not r["infact_answerable"] else "authentic")
            how = "rule" if r["by_rule"] else "LLM"
            L += [f"**claim {r['claim_id']}** · `{r['relation']}` ({how}) · {tag} · "
                  f"basis `{r['mo_basis']}` · confidence {r['mo_confidence']}", "",
                  f"*Q:* {r['question']}", "",
                  f"*InFact ({side}):* {r['infact_answer']}", "",
                  f"*model-only:* {r['mo_answer']}", "",
                  f"*adjudicator:* {r['relation_reason']}", "",
                  f"*merged:* {r['merged']}", "", "---", ""]

    report = run_dir / "exp06_report.md"
    report.write_text("\n".join(L))
    print(f"\nclean {pct(k_c, n_c)} vs poisoned {pct(k_p, n_p)} -> {report}")


if __name__ == "__main__":
    main()
