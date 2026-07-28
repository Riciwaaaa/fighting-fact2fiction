"""
TEMPORARY PROBE, part 4 -- the CONTROLLED three-way comparison.

Part 3 compared MO against the clean run's questions and against the poisoned run's
questions. Those are two independent samples of InFact's question generation (verified:
stages 1&2 read only `doc.claim`, so poisoning cannot affect them -- but the LLM samples
different wording each run, and ~10-13% of questions get dropped at stages 3&4 when they
turn out unanswerable). So the two conditions never shared a single question.

This run removes that residual confound: it takes the questions from the POISONED run --
for which the poisoned answers and the model-only answers already exist -- and re-runs only
InFact stages 3&4 (`approach_question_batch`: query generation, retrieval, answering)
against the CLEAN knowledge base. All three parties then answer the identical question set.

  question (fixed)  -->  clean-KB answer     (this script)
                    -->  poisoned-KB answer  (already have, part 3)
                    -->  model-only answer   (already have, part 3)

Stages 1&2 and 5&6 are never invoked; a FactChecker is built only to obtain a configured
`procedure` object, whose approach_question_batch is called directly.

Reads _inspect/conflict_probe.json. Writes _inspect/controlled_conflict.{md,json}.
Run under /home/ubuntu/.venv312/bin/python3.12 (DEFAME env, clean KB on disk).
"""

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAME_DIR = REPO_ROOT / "DEFAME"
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
OUT_DIR = REPO_ROOT / "_inspect"

sys.path.insert(0, str(EXPERIMENTS_DIR))
from fusion_common import call_json, set_model  # noqa: E402
from tmp_conflict_probe import ADJUDICATE_PROMPT, _valid_adj  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-json", type=str, default=str(OUT_DIR / "conflict_probe.json"))
    parser.add_argument("--fc-model", type=str, default="mimo_v25_pro")
    parser.add_argument("--adj-model", type=str, default="xiaomi/mimo-v2.5-pro")
    parser.add_argument("--claims", type=str, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out-prefix", type=str, default="controlled_conflict")
    args = parser.parse_args()

    set_model(args.adj_model)
    records = json.load(open(args.probe_json))
    if args.claims:
        want = {int(x) for x in args.claims.split(",")}
        records = [r for r in records if r["claim_id"] in want]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    os.chdir(DEFAME_DIR)
    sys.path.insert(0, str(DEFAME_DIR))
    from infact.common.content import Content
    from infact.common.claim import Claim
    from infact.common.document import FCDocument
    from infact.common.logger import Logger
    from infact.fact_checker import FactChecker
    from infact.eval.benchmark import AVeriTeCBinary

    logger = Logger(print_log_level="warning")
    # Built only to get a configured `procedure`; stages 1&2 and 5&6 are never called.
    # search_engines points at the on-disk AVeriTeC KB, which is CLEAN -- the attack only
    # ever poisons an in-memory copy.
    fc = FactChecker(
        llm=args.fc_model,
        search_engines=dict(averitec_kb=dict(variant="dev")),
        procedure_variant="infact",
        max_iterations=3,
        logger=logger,
        class_definitions=AVeriTeCBinary.class_definitions,
        extra_judge_rules=AVeriTeCBinary.extra_judge_rules,
    )
    kb = fc.actor.tools[0].search_apis["averitec_kb"]
    print("Clean KB ready.", flush=True)

    out = []
    for rec in records:
        cid = rec["claim_id"]
        t0 = time.perf_counter()
        pois_rows = [r for r in rec["rows"] if r["side"] == "poisoned"]
        questions = [r["question"] for r in pois_rows]
        if not questions:
            continue

        try:
            kb.current_claim_id = cid
            content = Content(text=rec["claim"])
            doc = FCDocument(claim=Claim(text=rec["claim"], original_context=content))
            qa = fc.procedure.approach_question_batch(questions, doc)
        except Exception as e:  # noqa: BLE001
            print(f"[{cid}] FAILED: {e}", flush=True)
            traceback.print_exc()
            continue

        clean_by_q = {t["question"]: t for t in qa}

        # Adjudicate MO vs the clean-KB answer to the SAME question.
        #
        # Questions the clean KB could NOT answer are no longer skipped. InFact drops them
        # silently (stages 3&4 return None; see base.py:26,64-65,71,109-119), which used to take
        # them out of the denominator entirely -- exactly the cases where retrieval failed and
        # model-only memory is most likely to carry signal. They are now resolved by rule rather
        # than by the LLM, because the comparison is structural and admits no ambiguity:
        #   clean KB found nothing + model-only has no recollection -> both empty-handed: agree
        #   clean KB found nothing + model-only has an answer       -> asymmetry:         conflict
        def adj(row):
            if not row.get("mo_answer"):
                return None
            c = clean_by_q.get(row["question"])
            if c is None:
                empty_handed = row.get("mo_basis") == "no_recollection"
                return {"relation": "agree" if empty_handed else "conflict",
                        "reason": ("the clean knowledge base could not answer and model-only has "
                                   "no recollection either" if empty_handed else
                                   "the clean knowledge base could not answer, but model-only "
                                   f"gave an answer on the basis of {row.get('mo_basis')}"),
                        "by_rule": True}
            return call_json(
                ADJUDICATE_PROMPT
                .replace("[CLAIM]", rec["claim"])
                .replace("[QUESTION]", row["question"])
                .replace("[INFACT_ANSWER]", c["answer"])
                .replace("[MO_ANSWER]", row["mo_answer"]),
                _valid_adj)

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            adjs = list(ex.map(adj, pois_rows))

        rows = []
        for row, a in zip(pois_rows, adjs):
            c = clean_by_q.get(row["question"])
            rows.append({
                "question": row["question"],
                "is_fake_in_poisoned": row["is_fake"],
                "poisoned_answer": row["infact_answer"],
                "poisoned_relation": row["relation"],
                "clean_answer": (c or {}).get("answer"),
                "clean_url": (c or {}).get("url"),
                "clean_answerable": c is not None,
                "clean_relation": (a or {}).get("relation"),
                "clean_relation_reason": (a or {}).get("reason"),
                "clean_relation_by_rule": bool((a or {}).get("by_rule")),
                "mo_answer": row["mo_answer"],
                "mo_premise": row["mo_premise"],
                "mo_basis": row.get("mo_basis"),
            })

        def rate(key):
            comp = [r for r in rows if r[key] in ("agree", "conflict")]
            return sum(1 for r in comp if r[key] == "conflict"), len(comp)

        kc, nc = rate("clean_relation")
        kp, np_ = rate("poisoned_relation")
        print(f"[{cid}] same {len(questions)} questions | clean-KB answered "
              f"{len(qa)}/{len(questions)} | MO-vs-clean {kc}/{nc} conflict | "
              f"MO-vs-poisoned {kp}/{np_} conflict ({time.perf_counter()-t0:.0f}s)", flush=True)

        out.append({"claim_id": cid, "claim": rec["claim"],
                    "gold_label": rec["gold_label"],
                    "clean_verdict": rec["clean_verdict"],
                    "poisoned_verdict": rec["poisoned_verdict"],
                    "attack_flipped": rec["attack_flipped"],
                    "n_questions": len(questions), "n_clean_answered": len(qa),
                    "rows": rows})
        with open(OUT_DIR / f"{args.out_prefix}.json", "w") as f:
            json.dump(out, f, indent=2)

    # ── aggregate ───────────────────────────────────────────────────────────────
    allrows = [r for o in out for r in o["rows"]]

    def agg(rows, key):
        comp = [r for r in rows if r[key] in ("agree", "conflict")]
        k = sum(1 for r in comp if r[key] == "conflict")
        return k, len(comp), (k / len(comp) if comp else float("nan"))

    kc, nc, rc = agg(allrows, "clean_relation")
    kp, np_, rp = agg(allrows, "poisoned_relation")

    L = ["# Controlled three-way comparison -- identical questions for all parties", "",
         "Part 3's clean and poisoned conditions never shared a question (two independent "
         "samples of InFact's question generation). Here the question set is **fixed**: the "
         "questions from each claim's poisoned run were re-answered by InFact stages 3&4 "
         "against the **clean** knowledge base, so the clean-KB answer, the poisoned-KB "
         "answer and the model-only answer all address the identical question.", "",
         f"Sample: **{len(out)} claims**, **{len(allrows)} questions**.", "",
         "---", "", "## Headline -- same questions, both conditions", "",
         "| model-only compared against | comparable | conflicts | **conflict rate** |",
         "|---|---|---|---|",
         f"| **clean** KB answers | {nc} | {kc} | **{rc:.1%}** |",
         f"| **poisoned** KB answers | {np_} | {kp} | **{rp:.1%}** |",
         "", f"Difference: **{rp - rc:+.1%}**.", ""]

    fk = [r for r in allrows if r["is_fake_in_poisoned"]]
    au = [r for r in allrows if not r["is_fake_in_poisoned"]]
    L += ["### Split by whether the poisoned run's evidence was planted", "",
          "`is_fake` is withheld from every prompt; used only here.", "",
          "| poisoned-run evidence | vs clean KB | vs poisoned KB |", "|---|---|---|"]
    for nm, s in [("planted", fk), ("authentic", au)]:
        k1, n1, r1 = agg(s, "clean_relation")
        k2, n2, r2 = agg(s, "poisoned_relation")
        L.append(f"| {nm} (n={len(s)}) | {k1}/{n1} = {r1:.1%} | {k2}/{n2} = {r2:.1%} |")

    n_unans = sum(1 for r in allrows if not r["clean_answerable"])
    L += ["", "### Answerability", "",
          f"The clean KB could not answer **{n_unans}/{len(allrows)}** "
          f"({n_unans/len(allrows):.0%}) of the questions the poisoned KB answered. "
          f"Planted evidence makes questions answerable that the genuine corpus cannot "
          f"support -- itself a poisoning signal.", ""]

    flip = [r for o in out if o["attack_flipped"] for r in o["rows"]]
    noflip = [r for o in out if not o["attack_flipped"] for r in o["rows"]]
    L += ["### By whether the attack flipped the verdict", "",
          "| subset | vs clean KB | vs poisoned KB |", "|---|---|---|"]
    for nm, s in [("attack flipped", flip), ("attack did not flip", noflip)]:
        k1, n1, r1 = agg(s, "clean_relation")
        k2, n2, r2 = agg(s, "poisoned_relation")
        L.append(f"| {nm} | {k1}/{n1} = {r1:.1%} | {k2}/{n2} = {r2:.1%} |")

    L += ["", "---", "", "## Per claim", "",
          "| claim | flipped | questions | clean KB answered | MO vs clean | MO vs poisoned |",
          "|---|---|---|---|---|---|"]
    for o in out:
        k1, n1, r1 = agg(o["rows"], "clean_relation")
        k2, n2, r2 = agg(o["rows"], "poisoned_relation")
        L.append(f"| {o['claim_id']} | {'yes' if o['attack_flipped'] else 'no'} | "
                 f"{o['n_questions']} | {o['n_clean_answered']} | "
                 f"{k1}/{n1}" + (f" ({r1:.0%})" if n1 else "") + f" | {k2}/{n2}" +
                 (f" ({r2:.0%})" if n2 else "") + " |")

    L += ["", "---", "",
          "## Cases where model-only agrees with the clean KB but conflicts with the poisoned KB",
          "", "These are the cleanest demonstrations of the defense premise: same question, "
          "internal knowledge tracks the genuine corpus and rejects the planted one.", ""]
    shown = 0
    for o in out:
        for r in o["rows"]:
            if (r["clean_relation"] == "agree" and r["poisoned_relation"] == "conflict"
                    and shown < 10):
                L += [f"**claim {o['claim_id']}** -- "
                      f"{'planted' if r['is_fake_in_poisoned'] else 'authentic'} evidence", "",
                      f"*Q:* {r['question']}", "",
                      f"*clean KB:* {(r['clean_answer'] or '')[:350]}", "",
                      f"*poisoned KB:* {(r['poisoned_answer'] or '')[:350]}", "",
                      f"*model-only:* {(r['mo_answer'] or '')[:350]}", "", "---", ""]
                shown += 1

    (OUT_DIR / f"{args.out_prefix}.md").write_text("\n".join(L))
    print(f"\nCONTROLLED: MO vs clean {rc:.1%} | MO vs poisoned {rp:.1%} (diff {rp-rc:+.1%})")
    print(f"Wrote {OUT_DIR / (args.out_prefix + '.md')}")


if __name__ == "__main__":
    main()
