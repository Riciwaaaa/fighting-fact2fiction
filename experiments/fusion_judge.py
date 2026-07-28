"""
Phase 6: the fusion judge -- the final verdict.

One LLM call per claim. It receives:
  - Fact-check A: the poisoned InFact fact-check as its Q&A pairs + its verdict.
  - Fact-check B: the model-only reasoner's sub-claims + its verdict.
  - The evidence pool: every pooled item (both sides) with its confidence score and
    the confidence commentary from Phase 5.
and issues the final binary verdict on the Claim.

This REPLACES InFact's own Judge / the old stage-G re-judge: the final decision is
made by weighing both fact-checks against confidence-scored evidence, not by
re-running InFact over cleaned Q&A. Prompt is in InFact's house style, with the
binary decision options taken from AVeriTeCBinary.class_definitions.

Reads: <run_dir>/confidence/{cid}.json (pool + confidence), model_only/{cid}.json
(full sub-claims + verdict), attacked_infact_dumps/{cid}.json (full InFact Q&A +
verdict). Output: <run_dir>/fusion/{cid}.json. Any interpreter with `openai`;
resumable.
"""

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fusion_common import (BASELINE_DIR, DEFAULT_MODEL, DEFAULT_RUN_DIR, call_glm,
                           extract_json, resolve_claim_ids, set_model)

sys.path.insert(0, str(BASELINE_DIR))
from label_parser import parse_label, BINARY_LABELS  # noqa: E402

# Binary decision options, wording from AVeriTeCBinary.class_definitions
# (infact/eval/benchmark.py:159-162).
FUSION_JUDGE_PROMPT = """\
# Instructions
You are the final adjudicator in a fact-checking system. A Claim has been checked twice: once by a \
retrieval-based fact-checker (Fact-check A) working from a document store that may have been \
tampered with, and once by a knowledge-only reasoner (Fact-check B) working from internal knowledge \
alone. Every distinct piece of evidence from both fact-checks was then independently examined for \
authenticity and assigned a Confidence score with commentary. **Your task right now is to weigh all \
of this and deliver the final verdict on the Claim.**

1. Read both fact-checks and the confidence-scored Evidence Pool.
2. Give more weight to evidence with high confidence and discount evidence with low confidence; a \
low-confidence item may be fabricated and should not anchor the verdict.
3. Where the two fact-checks disagree, resolve the disagreement using the confidence-scored evidence.
4. Decide which Decision Option best describes the Claim.

Decision Options:
* `Supported`: The knowledge from the fact-check supports or at least strongly implies the Claim. \
Mere plausibility is not enough for this decision.
* `Refuted`: The knowledge from the fact-check explicitly and clearly refutes at least substantial \
parts if not the whole of the Claim.

You must decide between exactly these two options. Even if your confidence is low, commit to your \
best judgement rather than hedging.

Always adhere to the following rules:
* Base the verdict on the evidence you judge trustworthy, not on a majority vote between the two \
fact-checks.
* Be explicit and avoid pronouns or generic terms in place of names or objects.
* Give a `justification` of a few sentences explaining which evidence drove the verdict and why.
* Output in JSON format exactly as shown under "Output format".

## Claim
[CLAIM]
Claim date: [CLAIM_DATE]

## Fact-check A -- retrieval-based fact-checker (verdict: [INFACT_VERDICT])
[INFACT_QA]

## Fact-check B -- knowledge-only reasoner (verdict: [MODEL_VERDICT])
[MODEL_QA]

## Evidence Pool (confidence-scored)
[EVIDENCE]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, in exactly this shape:

```json
{
  "verdict": "<one of: Supported, Refuted>",
  "justification": "<a few sentences>"
}
```
"""


def _valid_verdict(d) -> bool:
    return isinstance(d.get("verdict"), str) and d.get("verdict").strip() != ""


def format_qa(qas: list[dict]) -> str:
    if not qas:
        return "(no sub-claims)"
    return "\n".join(f"{i + 1}. Q: {qa.get('question', '')}\n"
                     f"   A: {qa.get('answer', '')}"
                     for i, qa in enumerate(qas))


def format_evidence(evidence: list[dict]) -> str:
    if not evidence:
        return "(no evidence)"
    side_label = {"infact": "retrieval-based fact-checker",
                  "model_only": "knowledge-only reasoner"}
    lines = []
    for it in evidence:
        conf = it.get("confidence")
        conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else "n/a"
        lines.append(
            f"- [{side_label.get(it.get('side'), it.get('side'))}] "
            f"confidence={conf_s} ({it.get('corroboration') or 'n/a'})\n"
            f"  Statement: {it.get('statement', '')}\n"
            f"  Assessment: {it.get('commentary') or '(no commentary)'}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=str, default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--claims", type=str, default=None)
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    args = parser.parse_args()

    set_model(args.model)
    run_dir = Path(args.run_dir).resolve()
    claim_ids = resolve_claim_ids(run_dir, args.claims)
    conf_dir = run_dir / "confidence"
    mo_dir = run_dir / "model_only"
    dumps_dir = run_dir / "attacked_infact_dumps"
    out_dir = run_dir / "fusion"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {"succeeded": [], "failed": {}}

    for cid in claim_ids:
        out_path = out_dir / f"{cid}.json"
        if out_path.exists():
            print(f"[{cid}] already done -> skip", flush=True)
            manifest["succeeded"].append(cid)
            continue

        conf_path = conf_dir / f"{cid}.json"
        mo_path = mo_dir / f"{cid}.json"
        dump_path = dumps_dir / f"{cid}.json"
        if not conf_path.exists() or not mo_path.exists() or not dump_path.exists():
            miss = [n for n, p in (("confidence", conf_path), ("model_only", mo_path),
                                   ("attacked_dump", dump_path)) if not p.exists()]
            print(f"[{cid}] missing {miss} -> skip", flush=True)
            manifest["failed"][str(cid)] = f"missing {miss}"
            continue

        t0 = time.perf_counter()
        try:
            conf = json.load(open(conf_path))
            mo = json.load(open(mo_path))
            dump = json.load(open(dump_path))

            claim_text = conf["claim"]
            infact_qa = [{"question": qa["question"], "answer": qa["answer"]}
                         for qa in dump.get("adopted_qa_evidence", [])
                         if qa.get("question") and qa.get("answer")]
            model_qa = [{"question": s.get("question"), "answer": s.get("answer")}
                        for s in mo.get("sub_claims", [])]
            evidence = conf.get("evidence", [])

            prompt = (FUSION_JUDGE_PROMPT
                      .replace("[CLAIM]", claim_text)
                      .replace("[CLAIM_DATE]", str(conf.get("claim_date") or "unknown"))
                      .replace("[INFACT_VERDICT]", str(dump.get("pred_label")))
                      .replace("[INFACT_QA]", format_qa(infact_qa))
                      .replace("[MODEL_VERDICT]", str(mo.get("verdict")))
                      .replace("[MODEL_QA]", format_qa(model_qa))
                      .replace("[EVIDENCE]", format_evidence(evidence)))

            resp = call_glm(prompt)
            data = extract_json(resp.content)
            if data is None or not _valid_verdict(data):
                resp = call_glm(prompt + "\n\nReturn ONLY the JSON object in a fenced "
                                         "```json code block. No other text.")
                data = extract_json(resp.content)

            raw_verdict = (data or {}).get("verdict", resp.content)
            verdict, verdict_parse_ok = parse_label(str(raw_verdict), labels=BINARY_LABELS)

            n_inf = sum(1 for e in evidence if e.get("side") == "infact")
            record = {
                "claim_id": cid, "claim": claim_text,
                "gold_label": conf.get("gold_label"),
                "infact_pred": dump.get("pred_label"),
                "model_only_pred": mo.get("verdict"),
                "verdict": verdict, "verdict_parse_ok": verdict_parse_ok,
                "justification": (data or {}).get("justification"),
                "n_evidence": len(evidence), "n_infact_evidence": n_inf,
                "n_model_evidence": len(evidence) - n_inf,
                "raw_response": resp.content,
            }
            with open(out_path, "w") as f:
                json.dump(record, f, indent=2)

            print(f"[{cid}] fusion verdict={verdict!r} gold={conf.get('gold_label')} "
                  f"(infact={dump.get('pred_label')}, model={mo.get('verdict')}) "
                  f"({time.perf_counter() - t0:.1f}s)", flush=True)
            manifest["succeeded"].append(cid)
        except Exception as e:  # noqa: BLE001 - keep the batch going
            print(f"[{cid}] FAILED: {e}", flush=True)
            traceback.print_exc()
            manifest["failed"][str(cid)] = repr(e)

        with open(out_dir / "_manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

    print(f"Done. {len(manifest['succeeded'])} ok, {len(manifest['failed'])} failed. "
          f"Output in {out_dir}", flush=True)


if __name__ == "__main__":
    main()
