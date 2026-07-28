"""
TEMPORARY PROBE, part 2 (not part of the run-05 pipeline).

Takes the sub-questions InFact posed and the model-only CoT answers produced by
tmp_probe_subq_modelonly.py, and runs InFact's OWN stages 5 & 6 over them:

  stage 5  Judge.judge(doc)              -> verdict
  stage 6  DocSummarizer.summarize(doc)  -> justification

The result is a "retrieval-free InFact": InFact's decomposition, InFact's judge, InFact's
justification writer, but with every answer coming from the reasoner's internal knowledge
instead of the (poisonable) knowledge base.

The document handed to the judge is built in InFact's exact reasoning format (see
procedure/variants/qa_based/base.py:approach_question_batch) so the judge sees the shape
it expects. The one honest deviation: there is no source URL, so the source line says so
explicitly rather than fabricating one.

Reads _inspect/subq_probe.json. Writes _inspect/subq_verdict.md + .json.
Run under /home/ubuntu/.venv312/bin/python3.12.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAME_DIR = REPO_ROOT / "DEFAME"
OUT_DIR = REPO_ROOT / "_inspect"

NO_SOURCE = "(no retrieved source: answered from the reasoner's internal knowledge)"


def norm(x):
    if not x:
        return None
    s = str(x).strip().lower()
    if s.startswith("support"):
        return "Supported"
    if s.startswith("refut"):
        return "Refuted"
    if "not enough" in s or s == "nei":
        return "Not Enough Evidence"
    if "conflict" in s or "cherry" in s:
        return "Conflicting Evidence/Cherrypicking"
    return s


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-json", type=str, default=str(OUT_DIR / "subq_probe.json"))
    parser.add_argument("--fc-model", type=str, default="mimo_v25_pro")
    parser.add_argument("--binary", action="store_true", default=True,
                        help="Restrict the judge to Supported/Refuted (matches run 05)")
    parser.add_argument("--four-class", dest="binary", action="store_false",
                        help="Use InFact's native 4-class label space instead")
    parser.add_argument("--drop-unanswered", action="store_true",
                        help="Mirror InFact's approach_question_batch, which drops questions it "
                             "could not answer. Default is to keep them: a model-only 'I know of "
                             "no record of this' is informative evidence, not a dead end.")
    args = parser.parse_args()

    records = json.load(open(args.probe_json))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    os.chdir(DEFAME_DIR)
    sys.path.insert(0, str(DEFAME_DIR))
    from infact.common.content import Content
    from infact.common.claim import Claim
    from infact.common.document import FCDocument
    from infact.common.logger import Logger
    from infact.common.modeling import make_model
    from infact.modules.judge import Judge
    from infact.modules.doc_summarizer import DocSummarizer
    from infact.eval.benchmark import AVeriTeC, AVeriTeCBinary

    bench = AVeriTeCBinary if args.binary else AVeriTeC
    logger = Logger(print_log_level="warning")
    llm = make_model(args.fc_model, logger=logger)
    judge = Judge(llm=llm, logger=logger,
                  classes=list(bench.class_definitions.keys()),
                  class_definitions=bench.class_definitions,
                  extra_rules=bench.extra_judge_rules)
    summarizer = DocSummarizer(llm, logger)

    out = []
    for r in records:
        t0 = time.perf_counter()
        cid = r["claim_id"]
        qas = r["qas"]
        used = [qa for qa in qas
                if not args.drop_unanswered or qa.get("status") == "answered"]

        content = Content(text=r["claim"])
        claim_obj = Claim(text=r["claim"], original_context=content)
        doc = FCDocument(claim=claim_obj)

        # InFact's exact Q&A reasoning block (base.py:approach_question_batch).
        blocks = [f"### {qa['question']}\n"
                  f"Answer: {qa.get('answer') or '(no answer)'}\n\n"
                  f"Source URL: {NO_SOURCE}"
                  for qa in used]
        doc.add_reasoning("## Initial Q&A\n" + "\n\n".join(blocks) if blocks
                          else "## Initial Q&A\n(no answers)")

        # --- stage 5: verdict ---
        label = judge.judge(doc)
        doc.add_reasoning("## Final Judgement\n" + judge.get_latest_reasoning())

        # --- stage 6: justification ---
        justification = summarizer.summarize(doc)
        doc.justification = justification
        doc.verdict = label

        gold = norm(r.get("gold_label"))
        pred = norm(label.value)
        ok = pred == gold
        print(f"[{cid}] verdict={pred!r} gold={gold!r} {'OK' if ok else 'WRONG'} "
              f"(used {len(used)}/{len(qas)} Q&A, {time.perf_counter()-t0:.1f}s)", flush=True)

        out.append({
            "claim_id": cid, "claim": r["claim"], "gold_label": gold,
            "verdict": pred, "correct": ok,
            "n_qa_used": len(used), "n_qa_total": len(qas),
            "n_answered": r["n_answered"], "n_uncertain": r["n_uncertain"],
            "n_unknown": r["n_unknown"],
            "judge_reasoning": judge.get_latest_reasoning(),
            "justification": justification,
            "qas": used,
        })

    with open(OUT_DIR / "subq_verdict.json", "w") as f:
        json.dump(out, f, indent=2)

    n_ok = sum(1 for o in out if o["correct"])
    label_space = "binary (Supported/Refuted)" if args.binary else "4-class"

    L = ["# Probe part 2 — retrieval-free InFact (stages 1,2 + model-only answers + 5,6)", "",
         "InFact's own question posing (stage 1&2), its own `Judge` (stage 5) and its own "
         "`DocSummarizer` (stage 6) — but every sub-question is answered from the reasoner's "
         "internal knowledge instead of the knowledge base. No retrieval anywhere in the loop.", "",
         f"Label space: **{label_space}**. "
         f"Unanswered questions were {'DROPPED (InFact-faithful)' if args.drop_unanswered else 'KEPT'}.",
         "",
         f"## Result: **{n_ok}/{len(out)} correct**", "",
         "| claim | gold | verdict | correct | Q&A used | answered / uncertain / unknown |",
         "|---|---|---|---|---|---|"]
    for o in out:
        L.append(f"| {o['claim_id']} | {o['gold_label']} | **{o['verdict']}** | "
                 f"{'✅' if o['correct'] else '❌'} | {o['n_qa_used']}/{o['n_qa_total']} | "
                 f"{o['n_answered']} / {o['n_uncertain']} / {o['n_unknown']} |")
    L += ["", "---", ""]

    for o in out:
        L += [f"## Claim {o['claim_id']} — gold `{o['gold_label']}` → verdict `{o['verdict']}` "
              f"{'✅' if o['correct'] else '❌'}", "",
              f"> {o['claim']}", "",
              "### Stage 6 — justification (InFact's DocSummarizer)", "",
              (o["justification"] or "(none)").strip(), "",
              "<details><summary>Stage 5 — the judge's raw reasoning</summary>", "",
              "````text", (o["judge_reasoning"] or "").strip(), "````", "", "</details>", "",
              "<details><summary>The Q&A document the judge saw</summary>", ""]
        for qa in o["qas"]:
            badge = {"answered": "✅", "uncertain": "🟡", "unknown": "🔴"}.get(qa.get("status"), "⚠️")
            L += [f"**{badge} {qa['question']}**", "", f"{qa.get('answer')}", ""]
        L += ["</details>", "", "---", ""]

    (OUT_DIR / "subq_verdict.md").write_text("\n".join(L))
    print(f"\n{n_ok}/{len(out)} correct. Wrote {OUT_DIR / 'subq_verdict.md'}")


if __name__ == "__main__":
    main()
