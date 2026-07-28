"""
TEMPORARY PROBE (not part of the run-05 pipeline).

Question being tested: when the sub-questions come from *InFact itself* -- not from the
model-only reasoner's own decomposition -- can a retrieval-free reasoner actually answer
them, or does it mostly plead insufficient knowledge?

This matters because the fusion defense assumes the model-only side carries usable signal
on the same sub-questions the retrieval side is working on. An earlier informal experiment
suggested model-only frequently cannot answer; this re-runs that test with InFact's real
machinery so the answer is not an artifact of a hand-rolled decomposition.

Pipeline (faithful to InFact stages 1 & 2, then our own stage):
  1&2. InFact's PoseQuestionsPrompt (infact/prompts/pose_questions.md, n=10) driven by the
       same LLM InFact uses, with questions extracted by InFact's own find_code_span().
       Runs through the DEFAME `infact` copy. No knowledge base is touched.
  3.   For each question: one model-only CoT call (no retrieval). The prompt requires an
       explicit `status` (answered / uncertain / unknown) so the "cannot answer" rate is
       measured rather than eyeballed, and forbids hedging as a default.

Outputs _inspect/subq_probe.md (readable) + _inspect/subq_probe.json (raw).
Run under /home/ubuntu/.venv312/bin/python3.12.
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAME_DIR = REPO_ROOT / "DEFAME"
BASELINE_DIR = REPO_ROOT / "baseline"
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
OUT_DIR = REPO_ROOT / "_inspect"

sys.path.insert(0, str(EXPERIMENTS_DIR))
from fusion_common import call_json, load_dev_claims, set_model  # noqa: E402

# Model-only CoT answering. Deliberately neutral: it must neither hedge by default nor
# invent specifics. `status` is the measurement -- it separates "I know this" from
# "I genuinely do not know" so the answerable-rate is a number, not an impression.
COT_ANSWER_PROMPT = """\
# Instructions
You are a fact-checker with broad world knowledge. A Claim is being fact-checked, and a \
Question was posed as part of that fact-check. **Your task right now is to answer that Question \
using only your own internal knowledge** -- you have no search engine, no retrieved documents, \
and no access to the fact-checking record.

1. Think through what you know that bears on the Question, step by step.
2. Answer the Question from that reasoning.
3. State honestly how well your knowledge actually covers the Question.

Always adhere to the following rules:
* Reason explicitly before answering. Your `reasoning` should show the specific facts you are \
drawing on, not a restatement of the Question.
* Answer directly when you do know. Do not hedge out of caution, and do not refuse merely \
because you lack a citation -- recalled knowledge is the point of this exercise.
* Do not invent specifics. If you do not know a date, number, or name, say so rather than \
guessing a plausible-looking one.
* Set `status` to exactly one of:
  * `answered`: you know enough to give a substantive answer you would stand behind.
  * `uncertain`: you have relevant partial knowledge but cannot fully settle the Question.
  * `unknown`: you genuinely have no usable knowledge bearing on the Question.
* Be explicit and avoid pronouns or generic terms in place of names or objects.
* Output in JSON format exactly as shown under "Output format".

## Claim
[CLAIM]
Claim date: [CLAIM_DATE]

## Question
[QUESTION]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, in exactly this shape:

```json
{
  "reasoning": "<your step-by-step reasoning from internal knowledge>",
  "answer": "<your answer, one sentence to one short paragraph>",
  "status": "<answered|uncertain|unknown>",
  "confidence": <number between 0.0 and 1.0>
}
```
"""


def _valid_answer(d) -> bool:
    return isinstance(d.get("status"), str) and isinstance(d.get("answer"), str)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=str, default=None,
                        help="Comma-separated dev claim ids (default: first 5 of the run-05 set)")
    parser.add_argument("--n-questions", type=int, default=10,
                        help="InFact uses 10 (procedure/variants/qa_based/infact.py:13)")
    parser.add_argument("--fc-model", type=str, default="mimo_v25_pro",
                        help="Model shorthand for InFact's question posing")
    parser.add_argument("--model-only-model", type=str, default="xiaomi/mimo-v2.5-pro",
                        help="OpenRouter id for the retrieval-free answerer")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    set_model(args.model_only_model)
    if "OPENROUTER_API_KEY" not in os.environ:
        sys.exit("OPENROUTER_API_KEY not set (baseline/.env)")

    if args.claims:
        claim_ids = [int(x) for x in args.claims.split(",")]
    else:
        manifest = json.load(open(REPO_ROOT / "experiments" / "runs" /
                                  "05_mimo_100claim_fusion" / "claims.json"))
        claim_ids = manifest["claim_ids"][:5]

    claims = load_dev_claims()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # InFact's own machinery for stages 1&2. cwd must be DEFAME (prompt templates and
    # config/api_keys.yaml resolve relative to it). No KnowledgeBase is constructed.
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
        claim_date = claims[cid].get("claim_date")
        gold = claims[cid].get("label")

        # --- InFact stages 1 & 2: interpretation + question posing -------------------
        content = Content(text=claim_text)
        claim_obj = Claim(text=claim_text, original_context=content)
        doc = FCDocument(claim=claim_obj)
        prompt = PoseQuestionsPrompt(doc, n_questions=args.n_questions)
        posing_response = llm.generate(prompt)
        questions = find_code_span(posing_response)
        print(f"[{cid}] InFact posed {len(questions)} questions", flush=True)

        # --- model-only CoT answering, one call per question -------------------------
        def answer(q):
            return call_json(
                COT_ANSWER_PROMPT
                .replace("[CLAIM]", claim_text)
                .replace("[CLAIM_DATE]", str(claim_date))
                .replace("[QUESTION]", q),
                _valid_answer)

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            answers = list(ex.map(answer, questions))

        qas = []
        for q, a in zip(questions, answers):
            a = a or {"reasoning": None, "answer": None, "status": "PARSE_FAILED",
                      "confidence": None}
            qas.append({"question": q, **a})

        n_ans = sum(1 for x in qas if x["status"] == "answered")
        n_unc = sum(1 for x in qas if x["status"] == "uncertain")
        n_unk = sum(1 for x in qas if x["status"] == "unknown")
        print(f"[{cid}] answered={n_ans} uncertain={n_unc} unknown={n_unk} "
              f"({time.perf_counter() - t0:.1f}s)", flush=True)

        records.append({
            "claim_id": cid, "claim": claim_text, "claim_date": claim_date,
            "gold_label": gold, "posing_response": posing_response,
            "n_questions": len(questions), "qas": qas,
            "n_answered": n_ans, "n_uncertain": n_unc, "n_unknown": n_unk,
        })

    with open(OUT_DIR / "subq_probe.json", "w") as f:
        json.dump(records, f, indent=2)

    # --- readable report -------------------------------------------------------------
    tot_q = sum(r["n_questions"] for r in records)
    tot_a = sum(r["n_answered"] for r in records)
    tot_u = sum(r["n_uncertain"] for r in records)
    tot_k = sum(r["n_unknown"] for r in records)
    pct = lambda n: f"{100 * n / tot_q:.0f}%" if tot_q else "n/a"

    L = ["# Probe — can model-only answer InFact's own sub-questions?", "",
         "InFact stages 1 & 2 (`pose_questions.md`, n=10, questions extracted with InFact's "
         "`find_code_span`) generate the sub-questions. A retrieval-free reasoner then answers "
         "each one with explicit chain-of-thought and a self-declared `status`.", "",
         "No knowledge base, no search, no retrieved documents are involved at any point.", "",
         "---", "", "## Headline", "",
         f"| | count | share |", "|---|---|---|",
         f"| questions posed | {tot_q} | |",
         f"| **answered** (substantive) | {tot_a} | {pct(tot_a)} |",
         f"| uncertain (partial knowledge) | {tot_u} | {pct(tot_u)} |",
         f"| **unknown** (no usable knowledge) | {tot_k} | {pct(tot_k)} |", "",
         "Per claim:", "",
         "| claim | gold | questions | answered | uncertain | unknown |", "|---|---|---|---|---|---|"]
    for r in records:
        L.append(f"| {r['claim_id']} | {r['gold_label']} | {r['n_questions']} | "
                 f"{r['n_answered']} | {r['n_uncertain']} | {r['n_unknown']} |")
    L += ["", "---", ""]

    for r in records:
        L += [f"## Claim {r['claim_id']} — gold `{r['gold_label']}`", "",
              f"> {r['claim']}", "", f"*Claim date: {r['claim_date']}*", "",
              f"**{r['n_questions']} questions posed by InFact** → "
              f"answered {r['n_answered']}, uncertain {r['n_uncertain']}, unknown {r['n_unknown']}",
              ""]
        L += ["<details><summary>InFact's raw interpretation + question-posing output</summary>",
              "", "````text", (r["posing_response"] or "").strip(), "````", "", "</details>", ""]
        for i, qa in enumerate(r["qas"]):
            badge = {"answered": "✅ answered", "uncertain": "🟡 uncertain",
                     "unknown": "🔴 unknown"}.get(qa["status"], f"⚠️ {qa['status']}")
            conf = qa.get("confidence")
            conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else "n/a"
            L += [f"### Q{i + 1}. {qa['question']}", "",
                  f"**{badge}** · confidence `{conf_s}`", "",
                  f"**Answer:** {qa.get('answer') or '(none)'}", "",
                  "<details><summary>chain of thought</summary>", "",
                  f"{qa.get('reasoning') or '(none)'}", "", "</details>", ""]
        L += ["---", ""]

    (OUT_DIR / "subq_probe.md").write_text("\n".join(L))
    print(f"\nTOTAL: {tot_q} questions | answered {tot_a} ({pct(tot_a)}) | "
          f"uncertain {tot_u} ({pct(tot_u)}) | unknown {tot_k} ({pct(tot_k)})")
    print(f"Wrote {OUT_DIR / 'subq_probe.md'} and {OUT_DIR / 'subq_probe.json'}")


if __name__ == "__main__":
    main()
