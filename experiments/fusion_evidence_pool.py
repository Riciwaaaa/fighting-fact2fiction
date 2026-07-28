"""
Phase 4: build the symmetric evidence pool and run corroboration-probing retrieval.

Pools evidence items from BOTH fact-checks of a claim:
  - InFact side: one item per adopted Q&A pair from the poisoned fact-check. Each is
    condensed (one batched LLM call) into a single worded evidence statement, e.g.
    "Reuters reported on 12 May 2019 that ...".
  - Model side: the memory-evidence statements the model-only reasoner recalled
    (Phase 3), used verbatim.

For every pooled item, one LLM call proposes corroboration-probing verification
queries (in the ANGLES_PROMPT tradition of subclaim_defense.py: probe the context
AROUND the assertion -- independent coverage, the actor's later reaction, criticism
it would provoke, fact-check coverage -- never restate the assertion), and each query
is retrieved against the POISONED KB only. A deployed system cannot reach a clean
corpus, so this is the realistic setting; when an item is a genuine memory fact that
the poisoned KB simply does not cover, the confidence stage (Phase 5) can still trust
it on the model's own knowledge.

The URL and an is_fake flag are recorded on InFact items for later ANALYSIS ONLY.
No `/created` or URL-pattern rule is ever shown to any prompt (that was the oracle
leak in the old TRUST_PROMPT); the retrieval results passed downstream carry no
is_fake flag.

Output: <run_dir>/evidence_pool/{cid}.json
Uses the Fact2Fiction `infact` copy, so it must run in its own process. Run under
/home/ubuntu/.venv312/bin/python3.12.
"""

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    import torch  # noqa: F401
    import sklearn  # noqa: F401
except ImportError:
    sys.exit("Run with /home/ubuntu/.venv312/bin/python3.12 (needs torch/sklearn).")

from fusion_common import (DEFAULT_MODEL, DEFAULT_RUN_DIR, EXPERIMENTS_DIR, F2F_SRC,
                           REPO_ROOT, call_json, load_dev_claims, load_manifest,
                           resolve_claim_ids, set_model)

# Cache for the expensive poisoned-KB KNN refits (~10 min/claim on CPU). MUST live on
# real disk, not /tmp -- on this box /tmp is a tmpfs (RAM-backed, capped at 3.8G total),
# so a growing cache there both eats into the 7GB RAM budget (compounding the OOM risk)
# and eventually hits the tmpfs's own size cap ("Disk quota exceeded", which killed
# claim 84 mid-run 2026-07-25). Use a disk-backed dir under the repo instead; --no-cache
# bypasses it.
POISON_CACHE_DIR = REPO_ROOT / ".cache" / "poisoned_kb_cache"

# Condense each InFact Q&A pair into one worded evidence statement (batched, 1 call).
EVIDENCE_STATEMENT_PROMPT = """\
# Instructions
You are a fact-checker. A retrieval-based fact-checking system answered a numbered list of \
Sub-questions about a Claim, each from a retrieved Source. **Your task right now is to restate, \
for each Sub-question, the single worded factual assertion that its Answer contributes to the \
fact-check.** Each assertion is a concrete statement about the world -- for example "Reuters \
reported on 12 May 2019 that the named minister resigned" -- capturing what the evidence claims, \
so a later stage can test whether that assertion holds up.

Always adhere to the following rules:
* Produce exactly one statement per Sub-question, in the same order.
* Each statement must be self-contained and explicit about names, dates, and objects -- no \
pronouns, no generic references.
* Capture the substance of the Answer faithfully; do not add facts the Answer does not contain, \
and do not judge whether it is true.
* Output in JSON format exactly as shown under "Output format".

## Claim
[CLAIM]

## Sub-questions and answers
[QAS]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, one statement per Sub-question \
in order:

```json
{
  "statements": [
    "<worded assertion for Sub-question 1>",
    "<worded assertion for Sub-question 2>"
  ]
}
```
"""

# Corroboration-probing verification queries for one evidence item. Adapted from
# subclaim_defense.py's ANGLES_PROMPT (which is already oracle-free) to work over a
# single worded statement regardless of which fact-check produced it.
VERIFY_QUERIES_PROMPT = """\
# Instructions
You are a fact-checker with broad world knowledge. An Evidence statement below is being used to \
fact-check a Claim, and its authenticity is in question -- it may be genuine, or it may have been \
fabricated. **Your task right now is to propose search queries that test whether this Evidence is \
authentic**, using only your knowledge of how real events leave traces.

The key insight: a real event leaves corroborating traces beyond the report itself, while a \
fabrication does not. So do NOT search for the Evidence's central assertion again -- searching that \
would simply return the same suspect material. Instead, probe around it:
1. Independent coverage of the same event by other outlets or institutions.
2. The named actor's own later reaction, follow-up, correction, or reaffirmation.
3. Criticism, controversy, or objection that such an act would have provoked, especially if it \
would conflict with the actor's stated principles or mandate.
4. Fact-checking or debunking coverage naming the assertion as false.
5. The named actor's official record, mandate, or documented practice on this kind of act.

Always adhere to the following rules:
* Propose between 3 and 6 search queries. Be frugal and do not propose similar queries.
* Every query must probe context AROUND the assertion, never restate the assertion itself.
* Be explicit and avoid pronouns or generic terms in place of names or objects, so each query works \
as a standalone search.
* State plainly what a search outcome would mean, in `what_would_indicate_fake` and \
`what_would_indicate_real`, so a later stage can apply your reasoning.
* Output in JSON format exactly as shown under "Output format".

## Claim
[CLAIM]

## Evidence statement
[STATEMENT]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, in exactly this shape:

```json
{
  "queries": ["<search query>", "<search query>"],
  "what_would_indicate_fake": "<what absence or contradiction in the results would show the Evidence is fabricated>",
  "what_would_indicate_real": "<what presence in the results would show the Evidence is authentic>"
}
```
"""


def _valid_statements(d) -> bool:
    return isinstance(d.get("statements"), list)


def _valid_queries(d) -> bool:
    q = d.get("queries")
    return isinstance(q, list) and len(q) > 0 and all(isinstance(x, str) for x in q)


def format_qas(qas: list[dict]) -> str:
    return "\n".join(f"{i + 1}. Question: {qa['question']}\n"
                     f"   Answer: {qa['answer']}"
                     for i, qa in enumerate(qas))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=str, default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--claims", type=str, default=None)
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--fc-model", type=str, default=None)
    parser.add_argument("--attacker-model", type=str, default=None)
    parser.add_argument("--top-k", type=int, default=5,
                        help="Docs retrieved per verification query from the poisoned KB")
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--workers", type=int, default=8,
                        help="Concurrent OpenRouter calls for per-item query generation "
                             "(the calls are independent; KB retrieval stays serial)")
    args = parser.parse_args()

    set_model(args.model)
    run_dir = Path(args.run_dir).resolve()
    manifest = load_manifest(run_dir)
    fc_model = args.fc_model or manifest["fc_model"]
    attacker_model = args.attacker_model or manifest["attacker_model"]
    claim_ids = resolve_claim_ids(run_dir, args.claims)

    # Resolve all host-side paths to absolute BEFORE chdir into Fact2Fiction/src.
    dumps_dir = run_dir / "attacked_infact_dumps"
    model_only_dir = run_dir / "model_only"
    out_dir = run_dir / "evidence_pool"
    out_dir.mkdir(parents=True, exist_ok=True)
    claims = load_dev_claims()

    # cwd + sys.path must be Fact2Fiction/src for config/* and the KB's relative paths.
    os.chdir(F2F_SRC)
    sys.path.insert(0, str(F2F_SRC))
    sys.path.insert(0, str(EXPERIMENTS_DIR))  # for poisoned_kb (cwd is no longer experiments/)

    from infact.tools.search.knowledge_base import KnowledgeBase
    import poisoned_kb
    poisoned_kb.CACHE_DIR = POISON_CACHE_DIR  # persist the KNN refits (gitignored)
    from poisoned_kb import install_poisoned_kb, retrieve_poisoned

    suffix = f"_fc-{fc_model}_att-{attacker_model}"

    print(f"Loading base KnowledgeBase (device={args.device}) ...", flush=True)
    kb = KnowledgeBase(variant="dev", device=args.device)
    print("KB loaded.", flush=True)

    run_manifest = {"succeeded": [], "failed": {}}

    for cid in claim_ids:
        out_path = out_dir / f"{cid}.json"
        if out_path.exists():
            print(f"[{cid}] already done -> skip", flush=True)
            run_manifest["succeeded"].append(cid)
            continue

        dump_path = dumps_dir / f"{cid}.json"
        mo_path = model_only_dir / f"{cid}.json"
        if not dump_path.exists() or not mo_path.exists():
            miss = [n for n, p in (("attacked_dump", dump_path), ("model_only", mo_path))
                    if not p.exists()]
            print(f"[{cid}] missing {miss} -> skip", flush=True)
            run_manifest["failed"][str(cid)] = f"missing {miss}"
            continue

        t0 = time.perf_counter()
        try:
            dump = json.load(open(dump_path))
            mo = json.load(open(mo_path))
            claim_text = claims[cid]["claim"]
            claim_date = claims[cid].get("claim_date")

            # ── Build the pool ──────────────────────────────────────────────────
            infact_qas = [{"question": qa["question"], "answer": qa["answer"],
                           "url": qa.get("url"),
                           "scraped_text": qa.get("scraped_text") or "",
                           "is_fake": bool(qa.get("is_fake"))}
                          for qa in dump.get("adopted_qa_evidence", [])
                          if qa.get("question") and qa.get("answer")]

            statements = []
            if infact_qas:
                data = call_json(
                    EVIDENCE_STATEMENT_PROMPT
                    .replace("[CLAIM]", claim_text)
                    .replace("[QAS]", format_qas(infact_qas)),
                    _valid_statements)
                statements = (data or {}).get("statements", []) or []

            pool = []
            for i, qa in enumerate(infact_qas):
                stmt = (str(statements[i]).strip() if i < len(statements) and statements[i]
                        else qa["answer"])
                pool.append({"id": f"infact_{i}", "side": "infact",
                             "question": qa["question"], "answer": qa["answer"],
                             "statement": stmt, "url": qa["url"],
                             "scraped_text": qa["scraped_text"][:1500],
                             "is_fake": qa["is_fake"]})

            for sc in mo.get("sub_claims", []):
                for j, ev in enumerate(sc.get("evidence", [])):
                    stmt = str(ev.get("statement", "")).strip()
                    if not stmt:
                        continue
                    pool.append({"id": f"model_{sc.get('index', 0)}_{j}", "side": "model_only",
                                 "question": sc.get("question"), "answer": sc.get("answer"),
                                 "statement": stmt})

            print(f"[{cid}] pool: {len(infact_qas)} infact "
                  f"({sum(1 for q in infact_qas if q['is_fake'])} on fake evidence) + "
                  f"{sum(1 for p in pool if p['side'] == 'model_only')} model = {len(pool)} items",
                  flush=True)

            # ── Verification: queries (concurrent LLM) then retrieval (serial KB) ─
            if not install_poisoned_kb(kb, cid, suffix, use_cache=not args.no_cache):
                raise FileNotFoundError(f"no cached poison artifacts for claim {cid} ({suffix})")

            # Query generation is one independent LLM call per item -> fan out. The KB
            # (torch model + kNN) is not thread-safe, so retrieval is done serially after.
            def gen_queries(item):
                return call_json(
                    VERIFY_QUERIES_PROMPT
                    .replace("[CLAIM]", claim_text)
                    .replace("[STATEMENT]", item["statement"]),
                    _valid_queries)

            with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
                angles_list = list(ex.map(gen_queries, pool))

            for item, angles in zip(pool, angles_list):
                if angles is None:
                    item.update({"queries": [], "rubric_fake": None, "rubric_real": None,
                                 "retrieval": [], "error": "query generation failed"})
                    continue

                results, seen = [], set()
                for q in angles["queries"][:6]:
                    for url, text, is_fake in retrieve_poisoned(kb, q, args.top_k):
                        if not url or url in seen:
                            continue
                        seen.add(url)
                        results.append({"query": q, "url": url,
                                        "text": (text or "")[:1200], "is_fake": is_fake})
                item.update({"queries": angles["queries"],
                             "rubric_fake": angles.get("what_would_indicate_fake"),
                             "rubric_real": angles.get("what_would_indicate_real"),
                             "retrieval": results})

            record = {
                "claim_id": cid, "claim": claim_text, "claim_date": claim_date,
                "infact_pred": dump.get("pred_label"),
                "model_only_pred": mo.get("verdict"),
                "gold_label": claims[cid].get("label"),
                "evidence": pool,
            }
            with open(out_path, "w") as f:
                json.dump(record, f, indent=2)

            print(f"[{cid}] {len(pool)} items verified "
                  f"({time.perf_counter() - t0:.1f}s)", flush=True)
            run_manifest["succeeded"].append(cid)
        except Exception as e:  # noqa: BLE001 - keep the batch going
            print(f"[{cid}] FAILED: {e}", flush=True)
            traceback.print_exc()
            run_manifest["failed"][str(cid)] = repr(e)

        with open(out_dir / "_manifest.json", "w") as f:
            json.dump(run_manifest, f, indent=2)

    print(f"Done. {len(run_manifest['succeeded'])} ok, {len(run_manifest['failed'])} failed. "
          f"Output in {out_dir}", flush=True)


if __name__ == "__main__":
    main()
