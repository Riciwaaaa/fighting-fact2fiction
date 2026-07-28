"""
Phase 3: model-only structured fact-check.

Fact-checks each claim using ONLY the model's internal knowledge -- no retrieval --
but organizes the output as InFact-style sub-claims (a question + an answer per
sub-claim) and attaches, to each sub-claim, the worded "evidence" the model recalled
from memory. "Evidence" here means a stated factual assertion the reasoner is relying
on (e.g. "A retrospective on the film was published by the BBC in 2019"), NOT a
retrieved document.

Two LLM calls per claim, mirroring evidence_rag_probe.py's split so the reasoning is
not distorted by having to co-emit its supporting evidence:
  1. MODEL_ONLY_STRUCTURED_PROMPT -> sub-claims (question + answer) + a binary verdict.
  2. MEMORY_EVIDENCE_PROMPT       -> 1-2 memory-evidence statements per sub-claim.

Output (one file per claim): <run_dir>/model_only/{cid}.json
Runs in parallel with the InFact tracks; no KB, no infact import -- any interpreter
with `openai`. Resumable (skips claims whose output already exists).
"""

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fusion_common import (BASELINE_DIR, DEFAULT_MODEL, DEFAULT_RUN_DIR, call_glm,
                           call_json, extract_json, load_dev_claims, resolve_claim_ids,
                           set_model)

sys.path.insert(0, str(BASELINE_DIR))
from label_parser import parse_label, BINARY_LABELS  # noqa: E402

# Wording follows InFact's own class_definitions (see infact/eval/benchmark.py:159).
DECISION_OPTIONS_BINARY = """\
* `Supported`: The claim is accurate and well-supported by your established knowledge.
* `Refuted`: The claim contradicts your established knowledge or is demonstrably false.

You must decide between exactly these two options. Even if your confidence is low, commit to your \
best judgement rather than hedging."""

# Call 1 -- structured fact-check. Style mirrors InFact's pose_questions_json.md /
# judge.md (# Instructions, numbered steps, `* ` rules, fenced JSON output).
MODEL_ONLY_STRUCTURED_PROMPT = """\
# Instructions
You are a fact-checker with broad world knowledge. Your task is to assess the veracity of a Claim \
**using only your own internal knowledge and reasoning** -- no external sources, no retrieved \
documents, no web search. Do this by following these steps:
1. Decompose the Claim into a small set of Sub-claims. Each Sub-claim is a specific yes/no or \
factual Question whose answer bears on the Claim's veracity.
2. Answer each Question from your internal knowledge, stating what you know and how confident you are.
3. From the answered Sub-claims, decide which Decision Option best describes the Claim.

Always adhere to the following rules:
* Propose between 2 and 6 Sub-claims. Each Question must probe a single, distinct aspect of the Claim.
* Answer each Question in one or two sentences. If your knowledge is thin on a Question, say so plainly.
* Be explicit and avoid pronouns or generic terms in place of names or objects, so each Sub-claim \
stands on its own.
* You must choose your final `verdict` from the Decision Options.
* Output in JSON format exactly as shown under "Output format".

## Decision Options
[DECISION_OPTIONS]

## Claim
[CLAIM]
Claim date: [CLAIM_DATE]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, in exactly this shape:

```json
{
  "sub_claims": [
    {"question": "<a specific question about the Claim>", "answer": "<what you know, from memory>"}
  ],
  "verdict": "<one of: Supported, Refuted>"
}
```
"""

# Call 2 -- memory evidence. Separated so the fact-check above is not distorted by
# having to co-emit its evidence. Style mirrors InFact's propose_queries.md.
MEMORY_EVIDENCE_PROMPT = """\
# Instructions
You are a fact-checker. A knowledge-only reasoner has answered a numbered list of Sub-claims about \
a Claim, each from internal memory. **Your task right now is to state, for each Sub-claim, the \
specific factual evidence from your own knowledge that backs its Answer.** Each evidence item is a \
concrete worded assertion about the world -- for example "A retrospective on the 1975 film was \
published by the BBC in 2019", or "The named senator voted against the bill in a recorded 2018 \
floor vote". It is NOT a search query and NOT a retrieved document; it is a fact you recall.

Always adhere to the following rules:
* Give between 1 and 2 evidence items for each Sub-claim, in the same order as the Sub-claims.
* Each evidence item must be a self-contained factual statement, explicit about names, dates, and \
objects -- no pronouns, no generic references.
* If you genuinely recall no specific supporting fact for a Sub-claim, return an empty list for it.
* Do not restate the Question; state the underlying fact you know.
* Output in JSON format exactly as shown under "Output format".

## Claim
[CLAIM]

## Sub-claims
[SUBCLAIMS]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose. `evidence` must have exactly one \
entry per Sub-claim, in order, each a list of statement strings:

```json
{
  "evidence": [
    ["<a factual statement backing Sub-claim 1>"],
    ["<a factual statement backing Sub-claim 2>", "<another for Sub-claim 2>"]
  ]
}
```
"""


def _valid_structured(d) -> bool:
    sc = d.get("sub_claims")
    return isinstance(sc, list) and len(sc) > 0


def _valid_evidence(d) -> bool:
    return isinstance(d.get("evidence"), list)


def format_subclaims(sub_claims: list[dict]) -> str:
    return "\n".join(f"{i + 1}. Question: {s.get('question', '')}\n"
                     f"   Answer: {s.get('answer', '')}"
                     for i, s in enumerate(sub_claims))


def factcheck_structured(claim: str, claim_date: str) -> dict:
    """Call 1: model-only structured fact-check -> sub-claims + binary verdict."""
    prompt = (MODEL_ONLY_STRUCTURED_PROMPT
              .replace("[DECISION_OPTIONS]", DECISION_OPTIONS_BINARY)
              .replace("[CLAIM]", claim)
              .replace("[CLAIM_DATE]", claim_date or "unknown"))
    data = call_json(prompt, _valid_structured)
    if data is None:
        return {"sub_claims": [], "verdict": None, "verdict_parse_ok": False, "parse_ok": False}

    sub_claims = [{"question": str(s.get("question", "")).strip(),
                   "answer": str(s.get("answer", "")).strip()}
                  for s in data["sub_claims"]
                  if str(s.get("question", "")).strip()]
    verdict, verdict_parse_ok = parse_label(str(data.get("verdict", "")), labels=BINARY_LABELS)
    return {"sub_claims": sub_claims, "verdict": verdict,
            "verdict_parse_ok": verdict_parse_ok, "parse_ok": True}


def attach_memory_evidence(claim: str, sub_claims: list[dict]) -> list[dict]:
    """Call 2: attach 1-2 memory-evidence statements to each sub-claim (best-effort)."""
    if not sub_claims:
        return sub_claims
    prompt = (MEMORY_EVIDENCE_PROMPT
              .replace("[CLAIM]", claim)
              .replace("[SUBCLAIMS]", format_subclaims(sub_claims)))
    data = call_json(prompt, _valid_evidence)
    ev_lists = data.get("evidence") if data else None
    for i, s in enumerate(sub_claims):
        s["index"] = i
        items = ev_lists[i] if isinstance(ev_lists, list) and i < len(ev_lists) else []
        if not isinstance(items, list):
            items = [items]
        s["evidence"] = [{"statement": str(x).strip()} for x in items if str(x).strip()]
    return sub_claims


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=str, default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--claims", type=str, default=None)
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    args = parser.parse_args()

    set_model(args.model)
    run_dir = Path(args.run_dir).resolve()
    claim_ids = resolve_claim_ids(run_dir, args.claims)
    out_dir = run_dir / "model_only"
    out_dir.mkdir(parents=True, exist_ok=True)

    claims = load_dev_claims()
    manifest = {"succeeded": [], "failed": {}}

    for cid in claim_ids:
        out_path = out_dir / f"{cid}.json"
        if out_path.exists():
            print(f"[{cid}] already done -> skip", flush=True)
            manifest["succeeded"].append(cid)
            continue

        t0 = time.perf_counter()
        try:
            claim_text = claims[cid]["claim"]
            claim_date = claims[cid].get("claim_date")
            gold_label = claims[cid].get("label")

            fc = factcheck_structured(claim_text, claim_date)
            sub_claims = attach_memory_evidence(claim_text, fc["sub_claims"])

            n_ev = sum(len(s.get("evidence", [])) for s in sub_claims)
            record = {
                "claim_id": cid, "claim": claim_text, "claim_date": claim_date,
                "gold_label": gold_label, "verdict": fc["verdict"],
                "verdict_parse_ok": fc["verdict_parse_ok"], "parse_ok": fc["parse_ok"],
                "sub_claims": sub_claims,
            }
            with open(out_path, "w") as f:
                json.dump(record, f, indent=2)

            print(f"[{cid}] verdict={fc['verdict']!r} gold={gold_label} "
                  f"n_subclaims={len(sub_claims)} n_evidence={n_ev} "
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
