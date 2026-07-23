"""
Part 2 of the "model-knowledge supplement" experiment (orchestrator).

For each claim it:
  A. runs a model-only fact-check (LLM internal knowledge) -> verdict + evidence bullets
     (deepseek/deepseek-v4-pro, reasoning max);
  B. loads the attacked-InFact dump (from run_attacked_infact.py) and, via an LLM
     comparison, finds the leads the model-only checker raised that the attacked
     InFact did NOT retrieve/use (ignoring InFact's fake /created sources);
  C. retrieves each such gap lead against the CLEAN KB to show whether a real,
     non-fake (possibly gold) document exists that InFact missed.

Uses the DEFAME copy of the `infact` package (via evidence_rag_probe), so it must
run in a separate process from run_attacked_infact.py (which uses the Fact2Fiction
copy). Communication is via the JSON dumps on disk.

Must run under /home/ubuntu/.venv312/bin/python3.12.
"""

import argparse
import csv
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = REPO_ROOT / "experiments"

# Import the prior experiment module and reuse its helpers. Importing it runs its
# module-level setup (baseline .env load, DEFAME chdir + KB import) exactly once.
sys.path.insert(0, str(EXPERIMENTS_DIR))
import evidence_rag_probe as erp  # noqa: E402

MODEL_ONLY_MODEL = "deepseek/deepseek-v4-pro"

DEFAME_DIR = erp.DEFAME_DIR
RESOURCES_DIR = DEFAME_DIR / "data" / "AVeriTeC" / "knowledge_base" / "dev" / "resources"

DEFAULT_CLAIM_IDS = [0, 3, 4, 5, 7, 8, 12, 16, 19, 20]


GAP_PROMPT_TEMPLATE = """\
You are auditing an automated fact-checking system that may have been fed \
poisoned/fabricated evidence. Your job is to find useful factual leads that a \
knowledge-only reasoner raised but that fact-checker did NOT actually cover with real evidence.

## Claim
[CLAIM]

## Model-only fact-check (internal knowledge, no retrieval)
Verdict: [MO_VERDICT]
Evidence the model-only checker relied on:
[MO_EVIDENCE]

## Fact-checker fact-check (retrieval-based, possibly poisoned)
Verdict: [IF_VERDICT]
Evidence the fact-checker adopted (each marked real or FAKE):
[IF_EVIDENCE]

## Task
Identify every distinct factual lead from the model-only evidence that the fact-checker did NOT \
substantively cover with a REAL (non-fake) source. Treat the fact-checker's FAKE sources as \
providing no genuine coverage. A lead counts as "missing" if the fact-checker never retrieved a \
real source addressing it, or only had a fake source on it, or the fact-checker was steered by a \
fake source that contradicts it. For each missing lead, write one web-search-style query \
to find a real source that would confirm or refute it.

Respond with ONLY a single fenced JSON code block, no other prose:

```json
{
  "gap_leads": [
    {"lead": "<atomic factual lead InFact missed>",
     "why_missing": "<not retrieved | only fake evidence | contradicted by fake>",
     "search_query": "<query to find a real source>"}
  ]
}
```
If InFact adequately covered everything with real evidence, return {"gap_leads": []}.
"""

REPAIR_SUFFIX = ("\n\nYour previous response could not be parsed as valid JSON. "
                 "Return ONLY the JSON object in a fenced ```json code block. No other text.")


def parse_gap_json(text: str) -> dict | None:
    """Best-effort extraction of {"gap_leads": [...]}. Empty list is valid."""
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = match.group(1) if match else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]
    if candidate is None:
        return None
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    leads = data.get("gap_leads")
    if not isinstance(leads, list):
        return None
    for item in leads:
        if not isinstance(item, dict) or not item.get("lead") or not item.get("search_query"):
            return None
    return data


def format_mo_evidence(evidence: list[dict]) -> str:
    if not evidence:
        return "(none)"
    return "\n".join(f"- {e['statement']}" for e in evidence)


def format_if_evidence(infact_evidence: list[dict]) -> str:
    if not infact_evidence:
        return "(none)"
    lines = []
    for e in infact_evidence:
        tag = "FAKE" if e.get("is_fake") else "real"
        summary = (e.get("summary") or "").strip().replace("\n", " ")
        lines.append(f"- [{tag}] {summary[:400]}  (source: {e.get('source')})")
    return "\n".join(lines)


def build_infact_evidence(dump: dict) -> list[dict]:
    """InFact's adopted evidence bullets: summary (the answer) + source + is_fake."""
    bullets = []
    for qa in dump.get("adopted_qa_evidence", []):
        bullets.append({
            "summary": qa.get("answer"),
            "source": qa.get("url"),
            "is_fake": bool(qa.get("is_fake")),
            "question": qa.get("question"),
        })
    return bullets


def detect_gaps(claim, mo_verdict, mo_evidence, if_verdict, if_evidence):
    prompt = (GAP_PROMPT_TEMPLATE
              .replace("[CLAIM]", claim)
              .replace("[MO_VERDICT]", str(mo_verdict))
              .replace("[MO_EVIDENCE]", format_mo_evidence(mo_evidence))
              .replace("[IF_VERDICT]", str(if_verdict))
              .replace("[IF_EVIDENCE]", format_if_evidence(if_evidence)))
    resp = erp.call_glm(prompt)
    data = parse_gap_json(resp.content)
    if data is None:
        resp = erp.call_glm(prompt + REPAIR_SUFFIX)
        data = parse_gap_json(resp.content)
    if data is None:
        return [], False
    return data["gap_leads"], True


def load_model_only_cache(path: Path) -> dict:
    """Optional reuse of an existing model-only run keyed by claim_id."""
    cache = {}
    if path and path.exists():
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    cache[rec["claim_id"]] = rec
                except (json.JSONDecodeError, KeyError):
                    continue
    return cache


def load_existing_claim_ids(jsonl_path: Path) -> set[int]:
    if not jsonl_path.exists():
        return set()
    ids = set()
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ids.add(json.loads(line)["claim_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=str, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--model", type=str, default=MODEL_ONLY_MODEL)
    parser.add_argument("--dumps", type=str,
                        default=str(EXPERIMENTS_DIR / "runs" / "01_deepseek_10claim" / "attacked_infact_dumps"))
    parser.add_argument("--out", type=str, default=str(EXPERIMENTS_DIR / "runs" / "01_deepseek_10claim"))
    parser.add_argument("--model-only-cache", type=str, default=None,
                        help="Optional evidence_rag.jsonl to reuse model-only results")
    parser.add_argument("--resume", action="store_true",
                        help="Append to existing jsonl/csv, skipping claim_ids already present "
                             "(default overwrites — only safe for a full claim set in one run)")
    parser.add_argument("--binary", action="store_true",
                        help="Restrict the model-only verdict to Supported/Refuted only")
    args = parser.parse_args()

    # cwd is DEFAME_DIR (set by importing erp); resolve relative paths against launch dir.
    def abspath(p):
        return p if os.path.isabs(p) else os.path.join(erp._original_cwd, p)

    dumps_dir = Path(abspath(args.dumps))
    out_dir = Path(abspath(args.out))
    out_dir.mkdir(parents=True, exist_ok=True)

    os.environ["MODEL_NAME"] = args.model
    if "OPENROUTER_API_KEY" not in os.environ:
        sys.exit("OPENROUTER_API_KEY not set (baseline/.env)")

    claim_ids = ([int(x) for x in args.claims.split(",")] if args.claims
                 else list(DEFAULT_CLAIM_IDS))

    print(f"Loading claims + clean KB (device={args.device}) ...")
    with open(DEFAME_DIR / "data" / "AVeriTeC" / "dev.json") as f:
        claims = json.load(f)
    kb = erp.KnowledgeBase(variant="dev", logger=None, device=args.device)
    print(f"KB restored: {len(kb.embedding_knns)} claim indices.")

    mo_cache = load_model_only_cache(Path(abspath(args.model_only_cache))
                                     if args.model_only_cache else None)

    jsonl_path = out_dir / "infact_supplement.jsonl"
    csv_path = out_dir / "infact_supplement_docs.csv"
    summary_path = out_dir / "infact_supplement_summary.json"

    existing_ids = load_existing_claim_ids(jsonl_path) if args.resume else set()
    if existing_ids:
        print(f"Resuming: {len(existing_ids)} claim(s) already in {jsonl_path}, skipping those.")
    claim_ids = [cid for cid in claim_ids if cid not in existing_ids]

    append = args.resume and jsonl_path.exists()
    jsonl_f = open(jsonl_path, "a" if append else "w")
    csv_f = open(csv_path, "a" if append else "w")
    csv_writer = csv.writer(csv_f)
    if not append:
        csv_writer.writerow([
            "claim_id", "gold_label", "model_only_verdict", "infact_attacked_verdict",
            "lead_idx", "lead", "why_missing", "search_query",
            "doc_rank", "doc_url", "doc_distance", "is_gold", "is_fake", "doc_snippet"])

    for cid in claim_ids:
        dump_path = dumps_dir / f"{cid}.json"
        if not dump_path.exists():
            print(f"[{cid}] no attacked-InFact dump at {dump_path} -> skip")
            continue
        with open(dump_path) as f:
            dump = json.load(f)

        claim_text = claims[cid]["claim"]
        gold_label = claims[cid].get("label")
        infact_verdict = dump.get("pred_label")
        infact_evidence = build_infact_evidence(dump)

        # Phase A: model-only fact-check (reasoning bullets + verdict). Reuse cache if provided.
        # Query generation (call 2) is deferred until we know the defense is actually needed.
        t0 = time.perf_counter()
        if cid in mo_cache:
            mo_verdict = mo_cache[cid].get("predicted_verdict")
            mo_steps = [e["statement"] for e in mo_cache[cid].get("evidence", [])]
            print(f"[{cid}] model-only from cache: {mo_verdict!r}", flush=True)
        else:
            fc = erp.factcheck_only(claim_text, binary=args.binary)
            mo_verdict = fc["verdict"]
            mo_steps = fc["steps"]
            print(f"[{cid}] model-only verdict={mo_verdict!r} "
                  f"n_steps={len(mo_steps)} ({time.perf_counter()-t0:.1f}s)", flush=True)

        # Skip gate: if the model-only verdict already agrees with the (poisoned) InFact verdict,
        # the model's knowledge offers no correction -> skip the whole defense (query gen + gap
        # detection + retrieval).
        defense_skipped = canon(mo_verdict) is not None and canon(mo_verdict) == canon(infact_verdict)

        if defense_skipped:
            mo_evidence = [{"statement": s, "search_query": None} for s in mo_steps]
            gap_leads, gap_ok, leads_out = [], True, []
            print(f"[{cid}] SKIP defense (model_only == infact: {mo_verdict!r}) | "
                  f"gold={gold_label}", flush=True)
        else:
            # Phase A (call 2): generate one search query per reasoning point.
            queries = erp.generate_queries(claim_text, mo_steps)
            mo_evidence = [{"statement": s, "search_query": q}
                           for s, q in zip(mo_steps, queries)]

            # Phase B: gap detection.
            gap_leads, gap_ok = detect_gaps(claim_text, mo_verdict, mo_evidence,
                                            infact_verdict, infact_evidence)
            print(f"[{cid}] gaps: {len(gap_leads)} (parse_ok={gap_ok}) | "
                  f"gold={gold_label} infact={infact_verdict} model_only={mo_verdict}", flush=True)

            # Phase C: retrieve gap leads against the clean KB.
            kb.current_claim_id = cid
            gold_urls = erp.load_gold_urls(RESOURCES_DIR, cid)
            leads_out = []
            for lead_idx, lead in enumerate(gap_leads):
                docs = erp.retrieve_with_scores(kb, lead["search_query"], args.top_k)
                for doc in docs:
                    doc["is_gold"] = doc["url"] in gold_urls
                    doc["is_fake"] = "created" in (doc["url"] or "")
                leads_out.append({
                    "lead": lead["lead"],
                    "why_missing": lead.get("why_missing"),
                    "search_query": lead["search_query"],
                    "retrieval": docs,
                })
                if docs:
                    for doc in docs:
                        csv_writer.writerow([
                            cid, gold_label, mo_verdict, infact_verdict,
                            lead_idx, lead["lead"], lead.get("why_missing"), lead["search_query"],
                            doc["rank"], doc["url"], doc["distance"],
                            doc["is_gold"], doc["is_fake"], doc["snippet"]])
                else:
                    csv_writer.writerow([
                        cid, gold_label, mo_verdict, infact_verdict,
                        lead_idx, lead["lead"], lead.get("why_missing"), lead["search_query"],
                        "", "", "", "", "", ""])

        record = {
            "claim_id": cid,
            "claim": claim_text,
            "gold_label": gold_label,
            "model_only_verdict": mo_verdict,
            "infact_attacked_verdict": infact_verdict,
            "defense_skipped": defense_skipped,
            "used_fake_evidence": dump.get("used_fake_evidence"),
            "used_original_evidence": dump.get("used_original_evidence"),
            "infact_evidence": infact_evidence,
            "model_only_evidence": mo_evidence,
            "gap_leads": leads_out,
            "gap_parse_ok": gap_ok,
        }
        record["synthesis"] = build_synthesis(record)
        jsonl_f.write(json.dumps(record) + "\n")
        jsonl_f.flush()
        csv_f.flush()

    jsonl_f.close()
    csv_f.close()
    print(f"Wrote {jsonl_path} and {csv_path}")
    write_summary(jsonl_path, summary_path)
    print(f"Wrote {summary_path}")


def build_synthesis(record: dict) -> str:
    n_leads = len(record["gap_leads"])
    n_gold = sum(1 for l in record["gap_leads"]
                 if any(d.get("is_gold") for d in l["retrieval"]))
    mo_correct = canon(record["model_only_verdict"]) == canon(record["gold_label"])
    if_correct = canon(record["infact_attacked_verdict"]) == canon(record["gold_label"])
    parts = [
        f"InFact adopted {record.get('used_fake_evidence')} fake / "
        f"{record.get('used_original_evidence')} real sources.",
        f"Model-only raised {n_leads} lead(s) InFact missed; "
        f"{n_gold} retrieve a gold doc from the clean KB.",
    ]
    if mo_correct and not if_correct:
        parts.append("Model-only internal knowledge reached the correct verdict where the "
                     "poisoned InFact did not.")
    return " ".join(parts)


def _norm(label):
    """Normalize a gold label to InFact's lowercase verdict space for comparison."""
    if label is None:
        return None
    return str(label).strip().lower()


def canon(label):
    """Canonicalize any label dialect (model-only AVeriTeC strings vs InFact Label.value)
    to one of Supported/Refuted/NEI/Conflicting, so agreement comparisons are dialect-proof.
    Binary Supported/Refuted fall out trivially; NEI/Conflicting need the mapping because
    InFact's values ('not enough information', 'conflicting evidence') differ from the AVeriTeC
    strings ('Not Enough Evidence', 'Conflicting Evidence/Cherrypicking')."""
    if label is None:
        return None
    s = str(label).strip().lower()
    if not s:
        return None
    if s in ("supported", "support"):
        return "Supported"
    if s in ("refuted", "refute"):
        return "Refuted"
    if "conflict" in s or "cherry" in s:
        return "Conflicting"
    if "not enough" in s or s == "nei":
        return "NEI"
    return s


def write_summary(jsonl_path: Path, summary_path: Path) -> None:
    if not jsonl_path.exists():
        return
    records = [json.loads(l) for l in open(jsonl_path) if l.strip()]
    n = len(records)

    def infact_wrong(r):
        return _norm(r["infact_attacked_verdict"]) != _norm(r["gold_label"])

    def mo_right(r):
        # model_only_verdict is in Title case (AVeriTeC labels); gold is too -> compare normalized.
        return _norm(r["model_only_verdict"]) == _norm(r["gold_label"])

    gap_counts = [len(r["gap_leads"]) for r in records]
    gap_with_gold = sum(
        1 for r in records for l in r["gap_leads"]
        if any(d.get("is_gold") for d in l["retrieval"]))
    total_leads = sum(gap_counts)

    summary = {
        "n_claims": n,
        "avg_used_fake_evidence": statistics.mean(
            [r.get("used_fake_evidence") or 0 for r in records]) if n else 0,
        "avg_used_original_evidence": statistics.mean(
            [r.get("used_original_evidence") or 0 for r in records]) if n else 0,
        "n_claims_infact_wrong": sum(1 for r in records if infact_wrong(r)),
        "avg_gap_leads_per_claim": statistics.mean(gap_counts) if n else 0,
        "total_gap_leads": total_leads,
        "gap_leads_with_gold_retrieval": gap_with_gold,
        # Headline: model-only internal knowledge is correct where poisoned InFact is wrong.
        "n_claims_model_only_corrects_infact": sum(
            1 for r in records if mo_right(r) and infact_wrong(r)),
        "gap_parse_fail": sum(1 for r in records if not r.get("gap_parse_ok", True)),
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
