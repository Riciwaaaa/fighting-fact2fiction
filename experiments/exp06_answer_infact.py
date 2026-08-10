"""
Experiment 06, passes B and C -- answer the shared question set with InFact stages 3 & 4.

    --kb clean      DEFAME env      -> answers_clean.json
    --kb poisoned   Fact2Fiction env -> answers_poisoned.json

Only stages 3 & 4 run (search query generation + answer generation). Stages 1 & 2 already ran
in pass A, and stages 5 & 6 (verdict, justification) are out of scope for this experiment.

THE POINT OF THIS SCRIPT: it calls `procedure.approach_question(q, doc)` once per question
instead of `approach_question_batch(questions, doc)`. The batch wrapper drops every question it
could not answer -- its docstring says so outright ("Unanswerable questions are dropped",
base.py:26) -- which silently removes from the denominator exactly the cases where retrieval
failed and model-only memory is most likely to carry signal. Calling the single-question entry
point lets us record that failure as a `NONE` row instead.

The two vendored `infact` copies cannot coexist in one interpreter, so the two `--kb` modes must
run as separate processes. They also differ in one API detail: Fact2Fiction's `approach_question`
returns `(qa_instance, search_results)` where DEFAME's returns a bare `qa_instance`.

The poisoned KB needs no monkey-patching. `install_poisoned_kb` sets `embedding_knns[cid]`,
`cached_resources`, `cached_resources_claim_id` and `current_claim_id`, and `_call_api` reads
exactly those -- so the ordinary retrieval path becomes poisoned on its own.

`is_fake` is derived from the answer's source URL for ANALYSIS ONLY. It never enters a prompt.

Run under /home/ubuntu/.venv312/bin/python3.12.
"""

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAME_DIR = REPO_ROOT / "DEFAME"
F2F_SRC = REPO_ROOT / "Fact2Fiction" / "src"
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
DEFAULT_RUN_DIR = EXPERIMENTS_DIR / "runs" / "06_symmetric_conflict"
POISON_CACHE_DIR = REPO_ROOT / ".cache" / "poisoned_kb_cache"

sys.path.insert(0, str(EXPERIMENTS_DIR))
from exp06_prompts import NONE_ANSWER  # noqa: E402


def build_fact_checker(fc_model: str, variant: str):
    """A FactChecker built solely to obtain a configured `procedure` and its KB.

    Stages 1&2 and 5&6 are never invoked; only `procedure.approach_question` is used.
    Works in either env because both `infact` copies expose the same constructor.
    """
    from infact.common.logger import Logger
    from infact.fact_checker import FactChecker
    from infact.eval.benchmark import AVeriTeCBinary

    logger = Logger(print_log_level="warning")
    fc = FactChecker(
        llm=fc_model,
        search_engines=dict(averitec_kb=dict(variant=variant)),
        procedure_variant="infact",
        max_iterations=3,
        logger=logger,
        class_definitions=AVeriTeCBinary.class_definitions,
        extra_judge_rules=AVeriTeCBinary.extra_judge_rules,
    )
    kb = fc.actor.tools[0].search_apis["averitec_kb"]
    return fc, kb


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb", choices=["clean", "poisoned"], required=True)
    parser.add_argument("--run-dir", type=str, default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--claims", type=str, default=None,
                        help="Comma-separated subset of the question file's claims")
    parser.add_argument("--fc-model", type=str, default="mimo_v25_pro")
    parser.add_argument("--attacker-model", type=str, default="deepseek_v4_flash")
    parser.add_argument("--variant", type=str, default="dev")
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--poison-rate", type=str, default="0.08",
                        help="Which attack run to read planted evidence from (--kb poisoned "
                             "only). The attack writes one directory per rate, so this selects "
                             "a directory; nothing else about the pipeline changes.")
    args = parser.parse_args()

    # Resolve every host path BEFORE chdir.
    run_dir = Path(args.run_dir).resolve()
    questions_path = run_dir / "questions.json"
    if not questions_path.exists():
        sys.exit(f"{questions_path} not found -- run exp06_pose_questions.py first")
    records = json.load(open(questions_path))
    if args.claims:
        want = {int(x) for x in args.claims.split(",")}
        records = [r for r in records if r["claim_id"] in want]
    out_path = run_dir / f"answers_{args.kb}.json"
    poison_cache = POISON_CACHE_DIR.resolve()

    poisoned = args.kb == "poisoned"
    src_dir = F2F_SRC if poisoned else DEFAME_DIR
    os.chdir(src_dir)
    sys.path.insert(0, str(src_dir))

    install_poisoned_kb = None
    if poisoned:
        sys.path.insert(0, str(EXPERIMENTS_DIR))  # poisoned_kb, now that cwd moved
        import poisoned_kb
        poisoned_kb.CACHE_DIR = poison_cache
        exp_rel = poisoned_kb.set_poison_rate(args.poison_rate)
        if not (src_dir / exp_rel).exists():
            sys.exit(f"{src_dir / exp_rel} not found -- run the attack at poison rate "
                     f"{args.poison_rate} first")
        print(f"Planted evidence from {exp_rel}", flush=True)
        from poisoned_kb import install_poisoned_kb

    from infact.common.content import Content
    from infact.common.claim import Claim
    from infact.common.document import FCDocument

    print(f"Building FactChecker ({args.kb} KB, device={args.device}) ...", flush=True)
    fc, kb = build_fact_checker(args.fc_model, args.variant)
    print("Ready.", flush=True)

    suffix = f"_fc-{args.fc_model}_att-{args.attacker_model}"
    out, failed = [], {}

    for rec in records:
        cid = rec["claim_id"]
        t0 = time.perf_counter()

        try:
            if poisoned:
                if not install_poisoned_kb(kb, cid, suffix, use_cache=True):
                    raise RuntimeError(f"no cached poison artifacts for claim {cid}{suffix}")
            else:
                kb.current_claim_id = cid

            content = Content(text=rec["claim"])
            doc = FCDocument(claim=Claim(text=rec["claim"], original_context=content))

            rows = []
            for q in rec["questions"]:
                # One question at a time -- see module docstring. `approach_question` returns
                # None (DEFAME) / (None, []) (Fact2Fiction) when stages 3&4 cannot answer.
                res = fc.procedure.approach_question(q, doc)
                qa = res[0] if isinstance(res, tuple) else res
                url = (qa or {}).get("url")
                rows.append({
                    "question": q,
                    "answerable": qa is not None,
                    "answer": (qa or {}).get("answer") or NONE_ANSWER,
                    "url": url,
                    # Analysis only. Never shown to any prompt.
                    "is_fake": bool(url and "/created" in url) if poisoned else None,
                })
        except Exception as e:  # noqa: BLE001 -- keep the batch going, record the gap
            print(f"[{cid}] FAILED: {e}", flush=True)
            traceback.print_exc()
            failed[str(cid)] = repr(e)
            continue

        n_ans = sum(1 for r in rows if r["answerable"])
        n_fake = sum(1 for r in rows if r["is_fake"])
        extra = f" | planted {n_fake}" if poisoned else ""
        print(f"[{cid}] answered {n_ans}/{len(rows)}{extra} "
              f"({time.perf_counter() - t0:.0f}s)", flush=True)

        out.append({**{k: rec[k] for k in
                       ("claim_id", "claim", "claim_date", "gold_label", "attack_flipped")},
                    "kb": args.kb, "rows": rows})
        with open(out_path, "w") as f:
            json.dump(out, f, indent=2)

    total = sum(len(r["rows"]) for r in out)
    answered = sum(1 for r in out for x in r["rows"] if x["answerable"])
    print(f"\n{args.kb} KB: {len(out)} claims, {total} questions, "
          f"{answered} answered, {total - answered} NONE -> {out_path}")
    if failed:
        print(f"FAILED claims: {failed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
