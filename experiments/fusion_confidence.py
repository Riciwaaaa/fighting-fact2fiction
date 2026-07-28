"""
Phase 5: per-evidence confidence commentary.

For each pooled evidence item (Phase 4), one LLM call rates how much to trust the
item -- its authenticity and reliability -- given the item's provenance (retrieved by
the fact-checker from its document store, vs recalled from the reasoner's own memory)
and the corroboration-probing retrieval results.

Prompt design (per the refactor requirements): the retrieval results are AUXILIARY.
If they do not corroborate the item but the model is independently confident from its
own knowledge, it may still assign high confidence; a genuine memory fact whose event
the poisoned KB simply does not cover should not be penalised for that alone. What
LOWERS confidence is the specific pattern of a claimed event that would necessarily
have left traces (independent coverage, reactions, criticism, fact-checks) for which
the results show none, or results that actively contradict the item. There is NO
`/created`/URL-pattern rule -- the is_fake flag is withheld from the prompt and kept
only for later analysis.

Modeled on InFact's judge.md / the old TRUST_PROMPT, minus the oracle rule.

Output: <run_dir>/confidence/{cid}.json  (the pool, each item extended with
confidence + corroboration + commentary). Any interpreter with `openai`; resumable.
"""

import argparse
import json
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fusion_common import (DEFAULT_MODEL, DEFAULT_RUN_DIR, call_json, resolve_claim_ids,
                           set_model)

CONFIDENCE_PROMPT = """\
# Instructions
You are a fact-checker assessing a single piece of Evidence used to check a Claim. The Evidence \
came from the Provenance stated below. Verification searches were run to look for the corroborating \
traces a real event would leave behind, and their Results are shown. **Your task right now is to \
decide how much to trust this Evidence -- its authenticity and reliability -- and to explain why.**

1. Judge the Evidence on its own merits first, using your internal knowledge of the world.
2. Then weigh the Verification Results and the Rubric as auxiliary signals.
3. Assign a `confidence` in [0.0, 1.0] that the Evidence is authentic and reliable, and classify \
the corroboration you found.

Always adhere to the following rules:
* The Verification Results are AUXILIARY, not decisive. If the Results do not corroborate the \
Evidence but you are independently confident from your own established knowledge that the assertion \
is true, you may still assign high confidence. A genuine fact whose event is simply not covered by \
the searched corpus should not be penalised for that absence alone.
* Lower your confidence when the assertion describes an event that WOULD necessarily have left \
traces -- independent coverage, the actor's reaction, criticism, fact-check coverage -- and the \
Results contain none of it, or when the Results actively contradict the assertion.
* Do not reason about source URLs, domains, or link formatting. Judge substance, not surface.
* Give a `commentary` of two or three sentences that cites both what you know and what the \
Results did or did not show.
* Output in JSON format exactly as shown under "Output format".

## Claim
[CLAIM]

## Evidence
[STATEMENT]

## Provenance
[PROVENANCE]

## Rubric
Indicates fabricated: [RUBRIC_FAKE]
Indicates authentic: [RUBRIC_REAL]

## Verification Results
[RESULTS]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, in exactly this shape:

```json
{
  "confidence": <number between 0.0 and 1.0>,
  "corroboration": "<corroborated|uncorroborated|contradicted>",
  "commentary": "<two or three sentences>"
}
```
"""

PROVENANCE_INFACT = ("This Evidence was retrieved by the retrieval-based fact-checker from its "
                     "document store while answering the sub-question: \"[QUESTION]\". The "
                     "fact-checker's source text was:\n[SOURCE]")
PROVENANCE_MODEL = ("This Evidence was recalled from the knowledge-only reasoner's own internal "
                    "knowledge (no retrieval), while answering the sub-question: \"[QUESTION]\".")


def _valid_confidence(d) -> bool:
    c = d.get("confidence")
    return isinstance(c, (int, float)) and 0.0 <= float(c) <= 1.0


def format_results(results: list[dict]) -> str:
    """Verification results WITHOUT any is_fake flag (no oracle leakage to the model)."""
    if not results:
        return "(no results were retrieved for any verification query)"
    return "\n".join(f"- [query: {r['query']}]\n"
                     f"  Source: {r['url']}\n"
                     f"  Content: {(r.get('text') or '')[:700]}"
                     for r in results)


def provenance_text(item: dict) -> str:
    if item["side"] == "infact":
        return (PROVENANCE_INFACT
                .replace("[QUESTION]", str(item.get("question") or ""))
                .replace("[SOURCE]", (item.get("scraped_text") or "")[:1200] or "(none)"))
    return PROVENANCE_MODEL.replace("[QUESTION]", str(item.get("question") or ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=str, default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--claims", type=str, default=None)
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--workers", type=int, default=8,
                        help="Concurrent OpenRouter calls (per-item ratings are independent)")
    args = parser.parse_args()

    set_model(args.model)
    run_dir = Path(args.run_dir).resolve()
    claim_ids = resolve_claim_ids(run_dir, args.claims)
    pool_dir = run_dir / "evidence_pool"
    out_dir = run_dir / "confidence"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {"succeeded": [], "failed": {}}

    for cid in claim_ids:
        out_path = out_dir / f"{cid}.json"
        if out_path.exists():
            print(f"[{cid}] already done -> skip", flush=True)
            manifest["succeeded"].append(cid)
            continue

        pool_path = pool_dir / f"{cid}.json"
        if not pool_path.exists():
            print(f"[{cid}] no evidence_pool -> skip", flush=True)
            manifest["failed"][str(cid)] = "no evidence_pool"
            continue

        t0 = time.perf_counter()
        try:
            record = json.load(open(pool_path))
            claim_text = record["claim"]

            # Each item's rating is an independent LLM call -> fan out across workers.
            def rate(item):
                return call_json(
                    CONFIDENCE_PROMPT
                    .replace("[CLAIM]", claim_text)
                    .replace("[STATEMENT]", item["statement"])
                    .replace("[PROVENANCE]", provenance_text(item))
                    .replace("[RUBRIC_FAKE]", str(item.get("rubric_fake")))
                    .replace("[RUBRIC_REAL]", str(item.get("rubric_real")))
                    .replace("[RESULTS]", format_results(item.get("retrieval", []))),
                    _valid_confidence)

            evidence = record.get("evidence", [])
            with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
                ratings = list(ex.map(rate, evidence))

            for item, data in zip(evidence, ratings):
                if data is None:
                    item.update({"confidence": None, "corroboration": None,
                                 "commentary": None, "confidence_parse_ok": False})
                else:
                    item.update({"confidence": float(data["confidence"]),
                                 "corroboration": data.get("corroboration"),
                                 "commentary": data.get("commentary"),
                                 "confidence_parse_ok": True})

            with open(out_path, "w") as f:
                json.dump(record, f, indent=2)

            confs = [i.get("confidence") for i in record.get("evidence", [])
                     if isinstance(i.get("confidence"), (int, float))]
            mean_c = sum(confs) / len(confs) if confs else float("nan")
            print(f"[{cid}] {len(record.get('evidence', []))} items rated, "
                  f"mean confidence={mean_c:.2f} ({time.perf_counter() - t0:.1f}s)", flush=True)
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
