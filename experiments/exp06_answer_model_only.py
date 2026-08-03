"""
Experiment 06, pass D -- answer the shared question set from internal knowledge alone.

No search engine, no retrieved documents, no knowledge of what either KB returned. The model
sees the claim, the claim date, and one question at a time.

TWO calls per question, deliberately kept apart:

    1. MO_ANSWER_PROMPT   -> answer, answer_basis, premise_status
    2. SELF_PROBE_PROMPT  -> confidence (0-100)

The second call is shown the question and the answer *text* and nothing else -- in particular not
the reasoning that produced the answer. Scoring used to happen inside the same generation, and on
claim 14 that let the model reason in a circle: it asserted UN officials had made statements,
declared `direct_recall` on the strength of its own assertion, then wrote "I recall it, so
trace_expectation is certainly_know" and scored 0.95, for something the clean corpus could not
support at all. Splitting the calls removes that loop by construction.

This follows the Self-Probing strategy from Xiong et al. (ICLR 2024), which they report as the
most consistent improvement over vanilla verbalized confidence on strong models -- vanilla being
the variant they show to be badly overconfident, with scores piling onto multiples of five in the
80-100 band. See experiments/reference/confidence_elicitation_prompts.md.

    answer_basis       direct_recall | inference | no_recollection -- where the answer came from.
                       `no_recollection` is the closed-book counterpart of a retriever returning
                       NONE, and pass E pairs the two structurally.

The scoring call reasons in prose about what an absence is worth -- would the reasoner
necessarily have encountered this fact, had it been so -- but emits no label for that judgement,
only the number. An earlier draft made it an explicit three-level field bound to score ranges,
and the label ended up deciding the number instead of the reasoning: across 17 synthetic cases
all seven top-tier rows landed within 3 points of each other. The buckets are gone.

Needs no `infact` copy and no KB, so it runs under any interpreter with `openai` installed and
can run concurrently with passes B and C.

Reads <run-dir>/questions.json, writes <run-dir>/answers_model_only.json.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
DEFAULT_RUN_DIR = EXPERIMENTS_DIR / "runs" / "06_symmetric_conflict"

sys.path.insert(0, str(EXPERIMENTS_DIR))
from fusion_common import call_json, set_model  # noqa: E402
from exp06_prompts import (MO_ANSWER_PROMPT, SELF_PROBE_PROMPT,  # noqa: E402
                           valid_mo, valid_probe, BASES)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=str, default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--claims", type=str, default=None)
    parser.add_argument("--model", type=str, default="xiaomi/mimo-v2.5-pro")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    set_model(args.model)
    run_dir = Path(args.run_dir).resolve()
    questions_path = run_dir / "questions.json"
    if not questions_path.exists():
        sys.exit(f"{questions_path} not found -- run exp06_pose_questions.py first")
    records = json.load(open(questions_path))
    if args.claims:
        want = {int(x) for x in args.claims.split(",")}
        records = [r for r in records if r["claim_id"] in want]
    out_path = run_dir / "answers_model_only.json"

    out = []
    for rec in records:
        t0 = time.perf_counter()

        def answer(q, _rec=rec):
            return call_json(
                MO_ANSWER_PROMPT
                .replace("[CLAIM]", _rec["claim"])
                .replace("[CLAIM_DATE]", str(_rec.get("claim_date")))
                .replace("[QUESTION]", q),
                valid_mo)

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            answers = list(ex.map(answer, rec["questions"]))

        # Second call per question. It is given the question and the answer text and nothing
        # else -- in particular not the reasoning that produced the answer, which is what stops
        # the model from scoring its own assertion on the strength of that same assertion.
        def probe(pair):
            q, a = pair
            if not a:
                return None
            return call_json(
                SELF_PROBE_PROMPT
                .replace("[QUESTION]", q)
                .replace("[ANSWER]", a["answer"]),
                valid_probe)

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            probes = list(ex.map(probe, zip(rec["questions"], answers)))

        rows = []
        for q, a, p in zip(rec["questions"], answers, probes):
            a, p = a or {}, p or {}
            rows.append({
                "question": q,
                "answer": a.get("answer"),
                "answer_basis": a.get("answer_basis"),
                "premise_status": a.get("premise_status"),
                "reasoning": a.get("reasoning"),
                # from the separate scoring call
                "confidence": p.get("confidence"),
                "probe_reasoning": p.get("reasoning"),
                "parse_failed": not a,
                "probe_failed": bool(a) and not p,
            })

        n_bad = sum(1 for r in rows if r["parse_failed"])
        n_pbad = sum(1 for r in rows if r["probe_failed"])
        bases = {b: sum(1 for r in rows if r["answer_basis"] == b) for b in BASES}
        confs = [r["confidence"] for r in rows if isinstance(r["confidence"], (int, float))]
        print(f"[{rec['claim_id']}] {len(rows)} answered "
              f"| recall {bases['direct_recall']} inference {bases['inference']} "
              f"none {bases['no_recollection']}"
              + (f" | conf mean {sum(confs) / len(confs):.2f}" if confs else "")
              + (f" | ANSWER FAILED {n_bad}" if n_bad else "")
              + (f" | PROBE FAILED {n_pbad}" if n_pbad else "")
              + f" ({time.perf_counter() - t0:.0f}s)", flush=True)

        out.append({**{k: rec[k] for k in
                       ("claim_id", "claim", "claim_date", "gold_label", "attack_flipped")},
                    "rows": rows})
        with open(out_path, "w") as f:
            json.dump(out, f, indent=2)

    total = sum(len(r["rows"]) for r in out)
    bad = sum(1 for r in out for x in r["rows"] if x["parse_failed"])
    pbad = sum(1 for r in out for x in r["rows"] if x["probe_failed"])
    print(f"\nmodel-only: {len(out)} claims, {total} answers ({2 * total} calls), "
          f"{bad} answer failures, {pbad} probe failures -> {out_path}")
    if bad:
        print("WARNING: parse failures become rows with a null answer; pass E will report them "
              "separately rather than dropping them.")


if __name__ == "__main__":
    main()
