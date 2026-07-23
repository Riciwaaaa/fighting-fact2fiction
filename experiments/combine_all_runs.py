"""
Combine every claim processed across all 4 experiment runs (experiments/runs/) into one
long-format CSV: one row per (run, claim, system).

Long/tidy format, not wide, because the 4 runs are structurally different -- different
models, different claim counts (10 / 27 / 27 / 100), and run 04 has no model-only baseline
at all. A wide one-row-per-claim table would need dozens of mostly-empty columns; long
format handles the heterogeneity cleanly and is trivial to pivot/filter afterward.

Read-only over already-produced result files -- no LLM/KB calls.

Output: experiments/runs/combined_all_runs.csv
Columns: run, claim_id, claim, gold_label, gold_justification, system, model, prediction,
         correct, justification
  - gold_justification = AVeriTeC's own "justification" field from dev.json (the human
    fact-checker's grounded justification for the gold label), joined by claim_id, same
    for every row of that claim regardless of run/system.
  - justification: for system=model_only, the bullet-point reasoning joined with " | "
    (one bullet per atomic point/statement the model reasoned through). For InFact-family
    systems with a stored prose justification (infact_poisoned, infact_clean,
    infact_baseline) that text is used directly. For infact_assisted_merge /
    infact_subclaim_verified, no single justification string is stored (they're structured
    traces, not prose) -- a compact machine-generated summary of the trace is used instead.
"""

import csv
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "experiments" / "runs"
DEV_JSON = REPO_ROOT / "DEFAME" / "data" / "AVeriTeC" / "dev.json"
FC_RESULTS = REPO_ROOT / "Fact2Fiction" / "src" / "fc_results" / "infact"
OUT_CSV = RUNS_DIR / "combined_all_runs.csv"


def normalize(label) -> str | None:
    """Same normalization as eval_table.py: map any label dialect to canonical space."""
    if label is None:
        return None
    s = str(label).strip().lower()
    if not s:
        return None
    if s in ("supported", "support"):
        return "Supported"
    if s in ("refuted", "refute"):
        return "Refuted"
    if s in ("nei", "not enough information", "not enough evidence", "not_enough_evidence"):
        return "Not Enough Evidence"
    if "conflict" in s or "cherry" in s:
        return "Conflicting Evidence/Cherrypicking"
    return None


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def parse_clean_report(report_path: Path) -> tuple[str | None, str | None]:
    """(verdict, justification) from an InFact fc_results doc -- '### Verdict:'/'### Justification'."""
    if not report_path.exists():
        return None, None
    text = report_path.read_text()
    vm = re.search(r"###\s*Verdict:\s*([^\n#]+)", text)
    jm = re.search(r"###\s*Justification\n(.*?)(?=\n##|\Z)", text, re.DOTALL)
    return (vm.group(1).strip() if vm else None), (jm.group(1).strip() if jm else None)


def bulletize(evidence: list[dict], sep: str = " | ") -> str:
    return sep.join(e["statement"] for e in evidence if e.get("statement"))


class RowSink:
    def __init__(self, gold: dict[int, dict]):
        self.gold = gold
        self.rows = []

    def add(self, run, claim_id, claim, system, model, prediction, justification):
        g = self.gold.get(claim_id, {})
        gold_label = g.get("label")
        pred_n, gold_n = normalize(prediction), normalize(gold_label)
        self.rows.append({
            "run": run, "claim_id": claim_id, "claim": claim or g.get("claim"),
            "gold_label": gold_label, "gold_justification": g.get("justification"),
            "system": system, "model": model,
            "prediction": pred_n if pred_n else prediction,
            "correct": (pred_n == gold_n) if (pred_n and gold_n) else None,
            "justification": justification,
        })


def add_run01(sink: RowSink):
    run = "01_deepseek_10claim"
    d = RUNS_DIR / run
    MODEL_ONLY = "deepseek/deepseek-v4-pro"
    INFACT_MODEL = "deepseek_v4_flash"

    # model_only: every claim evidence_rag.jsonl OR infact_supplement.jsonl covered.
    mo_by_cid = {}
    for r in load_jsonl(d / "evidence_rag.jsonl"):
        mo_by_cid[r["claim_id"]] = (r.get("predicted_verdict"), bulletize(r.get("evidence", [])))
    for r in load_jsonl(d / "infact_supplement.jsonl"):
        mo_by_cid[r["claim_id"]] = (r.get("model_only_verdict"),
                                    bulletize(r.get("model_only_evidence", [])))
    for cid, (verdict, just) in mo_by_cid.items():
        sink.add(run, cid, None, "model_only", MODEL_ONLY, verdict, just)

    # infact_poisoned + infact_clean: only the attacked-set claims have a poisoned dump.
    dumps_dir = d / "attacked_infact_dumps"
    for p in sorted(dumps_dir.glob("*.json")):
        if p.name == "_manifest.json":
            continue
        dump = json.load(open(p))
        cid = dump["claim_id"]
        sink.add(run, cid, dump.get("claim"), "infact_poisoned", INFACT_MODEL,
                 dump.get("pred_label"), dump.get("after_justification"))

    # infact_clean: for every claim_id we've seen so far (model_only ∪ poisoned), pull the
    # pristine pre-attack InFact prediction if a clean report exists for it.
    clean_dir = FC_RESULTS / INFACT_MODEL / "search_top_five" / "docs"
    for cid in sorted(mo_by_cid.keys() | {json.load(open(p))["claim_id"]
                                          for p in dumps_dir.glob("*.json")
                                          if p.name != "_manifest.json"}):
        v, j = parse_clean_report(clean_dir / str(cid))
        if v is not None:
            sink.add(run, cid, None, "infact_clean", INFACT_MODEL, v, j)


def add_run02(sink: RowSink):
    run = "02_mimo_27claim_4class"
    d = RUNS_DIR / run
    MODEL_ONLY = "xiaomi/mimo-v2.5-pro"
    INFACT_MODEL = "mimo_v25_pro"

    for r in load_jsonl(d / "infact_supplement.jsonl"):
        cid = r["claim_id"]
        sink.add(run, cid, r.get("claim"), "model_only", MODEL_ONLY,
                 r.get("model_only_verdict"), bulletize(r.get("model_only_evidence", [])))

    dumps_dir = d / "attacked_infact_dumps"
    claim_ids = set()
    for p in sorted(dumps_dir.glob("*.json")):
        if p.name == "_manifest.json":
            continue
        dump = json.load(open(p))
        cid = dump["claim_id"]
        claim_ids.add(cid)
        sink.add(run, cid, dump.get("claim"), "infact_poisoned", INFACT_MODEL,
                 dump.get("pred_label"), dump.get("after_justification"))

    clean_dir = FC_RESULTS / INFACT_MODEL / "search_top_five" / "docs"
    for cid in sorted(claim_ids):
        v, j = parse_clean_report(clean_dir / str(cid))
        if v is not None:
            sink.add(run, cid, None, "infact_clean", INFACT_MODEL, v, j)

    for p in sorted((d / "assisted_reverdict").glob("*.json")):
        if p.name == "_manifest.json":
            continue
        rec = json.load(open(p))
        summary = (f"additive-merge defense: {rec.get('n_poisoned_qa')} poisoned Q&A + "
                  f"{rec.get('n_new_qa')} new Q&A ({rec.get('n_new_fake')} fake); "
                  f"reproduced={rec.get('reproduced_pred')}")
        sink.add(run, rec["claim_id"], rec.get("claim"), "infact_assisted_merge", INFACT_MODEL,
                 rec.get("assisted_pred"), summary)


def add_run03(sink: RowSink):
    run = "03_mimo_27claim_binary"
    d = RUNS_DIR / run
    MODEL_ONLY = "xiaomi/mimo-v2.5-pro"
    INFACT_MODEL = "mimo_v25_pro"

    for r in load_jsonl(d / "infact_supplement.jsonl"):
        cid = r["claim_id"]
        sink.add(run, cid, r.get("claim"), "model_only", MODEL_ONLY,
                 r.get("model_only_verdict"), bulletize(r.get("model_only_evidence", [])))

    dumps_dir = d / "attacked_infact_dumps"
    claim_ids = set()
    for p in sorted(dumps_dir.glob("*.json")):
        if p.name == "_manifest.json":
            continue
        dump = json.load(open(p))
        cid = dump["claim_id"]
        claim_ids.add(cid)
        sink.add(run, cid, dump.get("claim"), "infact_poisoned", INFACT_MODEL,
                 dump.get("pred_label"), dump.get("after_justification"))

    # infact_clean reuses the SAME clean docs as run02: a clean baseline doesn't depend on
    # the attack's binary restriction, only on the fact-checker model.
    clean_dir = FC_RESULTS / INFACT_MODEL / "search_top_five" / "docs"
    for cid in sorted(claim_ids):
        v, j = parse_clean_report(clean_dir / str(cid))
        if v is not None:
            sink.add(run, cid, None, "infact_clean", INFACT_MODEL, v, j)

    for p in sorted((d / "assisted_reverdict").glob("*.json")):
        if p.name == "_manifest.json":
            continue
        rec = json.load(open(p))
        summary = (f"additive-merge defense: {rec.get('n_poisoned_qa')} poisoned Q&A + "
                  f"{rec.get('n_new_qa')} new Q&A ({rec.get('n_new_fake')} fake); "
                  f"reproduced={rec.get('reproduced_pred')}")
        sink.add(run, rec["claim_id"], rec.get("claim"), "infact_assisted_merge", INFACT_MODEL,
                 rec.get("assisted_pred"), summary)

    for p in sorted((d / "subclaim_defense").glob("*.json")):
        if p.name == "_manifest.json":
            continue
        rec = json.load(open(p))
        if rec.get("defense_skipped"):
            summary = f"skip-gate: model_only == infact ({rec.get('model_only_verdict')})"
        else:
            n_fab = sum(1 for v in rec.get("verifications", []) if v.get("trust") == "fabricated")
            summary = (f"sub-claim defense: {rec.get('n_verified')} sub-claims verified "
                      f"({n_fab} fabricated), {rec.get('n_revised')} revised, "
                      f"{rec.get('n_added')} added; reproduced={rec.get('reproduced_pred')}")
        sink.add(run, rec["claim_id"], rec.get("claim"), "infact_subclaim_verified", INFACT_MODEL,
                 rec.get("subclaim_verified_pred", rec.get("orig_pred")), summary)


def add_run04(sink: RowSink):
    run = "04_results_baseline_100claim"
    d = RUNS_DIR / run
    model_files = {
        "deepseek_v4_flash": "combined_results_deepseek_v4_flash_100.csv",
        "mimo_v25_pro": "combined_results_mimo_v25_pro_100.csv",
        "minimax_m3": "combined_results_minimax_m3_100.csv",
        "gemini_3.5_flash": "combined_results_gemini_3.5_flash.csv",
    }
    for model, fname in model_files.items():
        p = d / fname
        if not p.exists():
            continue
        with open(p) as f:
            for row in csv.DictReader(f):
                sink.add(run, int(row["sample_index"]), row.get("claim"), "infact_baseline",
                         model, row.get("predicted"), row.get("justification"))


def main():
    with open(DEV_JSON) as f:
        dev = json.load(f)
    gold = {i: {"claim": dev[i]["claim"], "label": dev[i]["label"],
               "justification": dev[i].get("justification")}
            for i in range(len(dev))}

    sink = RowSink(gold)
    add_run01(sink)
    add_run02(sink)
    add_run03(sink)
    add_run04(sink)

    sink.rows.sort(key=lambda r: (r["run"], r["claim_id"], r["system"]))

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["run", "claim_id", "claim", "gold_label",
                                          "gold_justification", "system", "model",
                                          "prediction", "correct", "justification"])
        w.writeheader()
        w.writerows(sink.rows)

    print(f"Wrote {len(sink.rows)} rows to {OUT_CSV}")
    by_run = {}
    for r in sink.rows:
        by_run.setdefault(r["run"], set()).add(r["claim_id"])
    for run, cids in sorted(by_run.items()):
        n_rows = sum(1 for r in sink.rows if r["run"] == run)
        print(f"  {run}: {len(cids)} distinct claims, {n_rows} rows")


if __name__ == "__main__":
    main()
