"""
Experiment 06, pass A -- pose the shared sub-question set.

Runs InFact's stages 1 & 2 (interpretation + question posing) ONCE per claim. The resulting
questions are then answered by all three systems (clean InFact, poisoned InFact, model-only),
so every comparison downstream is over an identical question set. Earlier probes compared the
clean run's questions against the poisoned run's questions -- two independent draws of a
stochastic generator -- which is the confound this pass exists to remove.

Stages 1 & 2 read only `doc.claim`; no KnowledgeBase is constructed and none is needed. That is
what makes a single shared question set legitimate: poisoning cannot influence what gets asked.

Requires EXACTLY `--n-questions` questions per claim. If a claim cannot produce that many after
`--max-attempts` tries, the run aborts rather than shipping a short set: a claim contributing 9
rows instead of 10 would silently skew every rate computed later, and silent shortfalls are the
exact class of bug this experiment was rebuilt to eliminate.

Writes <run-dir>/questions.json.
Run under /home/ubuntu/.venv312/bin/python3.12.
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAME_DIR = REPO_ROOT / "DEFAME"
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
DEFAULT_RUN_DIR = EXPERIMENTS_DIR / "runs" / "06_symmetric_conflict"

# Claims with cached poison artifacts, so pass C never re-invokes the attacker LLM.
DEFAULT_CLAIMS = [4, 6, 14, 20, 25, 3, 5, 8, 12, 17]

# `attack_flipped` is read off run 05, the end-to-end run that produced a verdict per claim under
# both knowledge bases: flipped means the clean fact-check got it right and the poisoned one did
# not. It was previously a hardcoded set covering only the original ten claims, which silently
# mislabelled every other claim as not-flipped.
#
# It is a stratification label for reporting and nothing more. In particular it is NOT this
# experiment's own measurement of whether the attack worked -- run 05 posed its own questions, so
# a claim can be flipped there and survive here (claim 14 does exactly that).
FLIP_SOURCE = EXPERIMENTS_DIR / "runs" / "05_mimo_100claim_fusion" / "eval_predictions.csv"

sys.path.insert(0, str(EXPERIMENTS_DIR))
from fusion_common import load_dev_claims  # noqa: E402


def load_flipped() -> set:
    if not FLIP_SOURCE.exists():
        print(f"WARNING: {FLIP_SOURCE} missing; attack_flipped will be null", file=sys.stderr)
        return None
    with open(FLIP_SOURCE) as f:
        return {int(r["claim_id"]) for r in csv.DictReader(f)
                if r["clean_infact"] == r["gold"] and r["f2f_poisoned_infact"] != r["gold"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=str, default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--claims", type=str, default=None,
                        help="Comma-separated claim ids (default: the fixed 10-claim set)")
    parser.add_argument("--n-questions", type=int, default=10)
    parser.add_argument("--fc-model", type=str, default="mimo_v25_pro")
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()

    claim_ids = ([int(x) for x in args.claims.split(",")] if args.claims
                 else list(DEFAULT_CLAIMS))
    run_dir = Path(args.run_dir).resolve()      # resolve before chdir
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / "questions.json"
    claims = load_dev_claims()
    flipped = load_flipped()

    # cwd must be DEFAME: prompt templates and config/api_keys.yaml resolve relative to it.
    os.chdir(DEFAME_DIR)
    sys.path.insert(0, str(DEFAME_DIR))
    from infact.common.content import Content
    from infact.common.claim import Claim
    from infact.common.document import FCDocument
    from infact.common.logger import Logger
    from infact.common.modeling import make_model
    from infact.prompts.prompt import PoseQuestionsPrompt
    from infact.utils.parsing import find_code_span

    logger = Logger(print_log_level="warning")
    llm = make_model(args.fc_model, logger=logger)

    records = []
    for cid in claim_ids:
        t0 = time.perf_counter()
        claim_text = claims[cid]["claim"]
        content = Content(text=claim_text)
        doc = FCDocument(claim=Claim(text=claim_text, original_context=content))
        prompt = PoseQuestionsPrompt(doc, n_questions=args.n_questions)

        questions, raw = [], None
        for attempt in range(1, args.max_attempts + 1):
            raw = llm.generate(prompt)
            questions = [q.strip() for q in find_code_span(raw) if q and q.strip()]
            if len(questions) >= args.n_questions:
                questions = questions[:args.n_questions]
                break
            print(f"[{cid}] attempt {attempt}: got {len(questions)}/{args.n_questions} "
                  f"questions, retrying", flush=True)

        if len(questions) != args.n_questions:
            sys.exit(f"[{cid}] FATAL: only {len(questions)} questions after "
                     f"{args.max_attempts} attempts. Refusing to continue with a short set -- "
                     f"it would skew every rate computed downstream.")

        print(f"[{cid}] {len(questions)} questions ({time.perf_counter() - t0:.0f}s)", flush=True)
        records.append({
            "claim_id": cid,
            "claim": claim_text,
            "claim_date": claims[cid].get("claim_date"),
            "gold_label": claims[cid].get("label"),
            "attack_flipped": (cid in flipped) if flipped is not None else None,
            "posing_response": raw,
            "questions": questions,
        })
        with open(out_path, "w") as f:
            json.dump(records, f, indent=2)

    total = sum(len(r["questions"]) for r in records)
    assert total == len(records) * args.n_questions, f"expected uniform sets, got {total}"
    print(f"\n{len(records)} claims x {args.n_questions} = {total} questions -> {out_path}")


if __name__ == "__main__":
    main()
