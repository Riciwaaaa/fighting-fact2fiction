"""
Wide-format combined CSV for run 03 (03_mimo_27claim_binary) ONLY: one row per claim,
with a prediction + justification column-pair per system.

Columns: claim_id, claim, gold_label,
         infact_clean_{prediction,justification},
         infact_poisoned_{prediction,justification},
         model_only_{prediction,justification},
         infact_assisted_merge_{prediction,justification},
         infact_subclaim_verified_{prediction,justification},
         gold_justification

Justification sources:
  - infact_clean / infact_poisoned: InFact's own prose justification, parsed from its report.
  - model_only: bullet points (atomic reasoning points) joined with " | ".
  - infact_assisted_merge: LEFT BLANK. rejudge_assisted.py (the additive-merge defense
    script) never captured Judge.latest_reasoning after calling judge.judge() -- only the
    predicted label and Q&A counts were persisted, so no prose justification exists for
    this system. Re-running would be needed to get it (5 claims: 0,3,4,6,8).
  - infact_subclaim_verified: built from the REAL per-sub-claim trust_reason text captured
    during verification (each fabricated/doubtful/trustworthy call's stated reason),
    joined into one justification -- this is genuine model output, not a synthesized count.

Read-only, no LLM/KB calls. Output: experiments/runs/03_mimo_27claim_binary/combined_wide.csv
"""

import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = REPO_ROOT / "experiments" / "runs" / "03_mimo_27claim_binary"
DEV_JSON = REPO_ROOT / "DEFAME" / "data" / "AVeriTeC" / "dev.json"
FC_RESULTS = REPO_ROOT / "Fact2Fiction" / "src" / "fc_results" / "infact" / "mimo_v25_pro" / \
    "search_top_five" / "docs"
OUT_CSV = RUN_DIR / "combined_wide.csv"


def normalize(label) -> str | None:
    if label is None:
        return None
    s = str(label).strip().lower()
    if s in ("supported", "support"):
        return "Supported"
    if s in ("refuted", "refute"):
        return "Refuted"
    if "conflict" in s or "cherry" in s:
        return "Conflicting Evidence/Cherrypicking"
    if "not enough" in s or s == "nei":
        return "Not Enough Evidence"
    return label


def load_jsonl(path: Path) -> dict[int, dict]:
    out = {}
    if not path.exists():
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            out[rec["claim_id"]] = rec
    return out


def load_json_dir(d: Path) -> dict[int, dict]:
    out = {}
    if not d.exists():
        return out
    for p in d.glob("*.json"):
        if p.name == "_manifest.json":
            continue
        rec = json.load(open(p))
        out[rec["claim_id"]] = rec
    return out


def parse_clean_report(report_path: Path) -> tuple[str | None, str | None]:
    import re
    if not report_path.exists():
        return None, None
    text = report_path.read_text()
    vm = re.search(r"###\s*Verdict:\s*([^\n#]+)", text)
    jm = re.search(r"###\s*Justification\n(.*?)(?=\n##|\Z)", text, re.DOTALL)
    return (vm.group(1).strip() if vm else None), (jm.group(1).strip() if jm else None)


def bulletize(evidence: list[dict]) -> str:
    return " | ".join(e["statement"] for e in evidence if e.get("statement"))


def subclaim_justification(rec: dict) -> str:
    if rec.get("defense_skipped"):
        return (f"Skip-gate: model_only agreed with poisoned InFact "
               f"({rec.get('model_only_verdict')}) -- defense not run, verdict unchanged.")
    parts = []
    for v in rec.get("verifications", []):
        trust = v.get("trust")
        reason = v.get("trust_reason")
        if trust and reason:
            parts.append(f"[{v.get('question', '')[:80]}] {trust}: {reason}")
    if rec.get("new_qa"):
        parts.append(f"Added {len(rec['new_qa'])} supplementary Q&A from material missing points.")
    return " | ".join(parts)


def main():
    with open(DEV_JSON) as f:
        dev = json.load(f)

    supplement = load_jsonl(RUN_DIR / "infact_supplement.jsonl")
    poisoned = load_json_dir(RUN_DIR / "attacked_infact_dumps")
    assisted = load_json_dir(RUN_DIR / "assisted_reverdict")
    subclaim = load_json_dir(RUN_DIR / "subclaim_defense")

    claim_ids = sorted(set(supplement) | set(poisoned) | set(assisted) | set(subclaim))

    rows = []
    for cid in claim_ids:
        gold = dev[cid]
        sup = supplement.get(cid, {})
        pdump = poisoned.get(cid, {})
        adump = assisted.get(cid, {})
        sdump = subclaim.get(cid, {})

        clean_v, clean_j = parse_clean_report(FC_RESULTS / str(cid))

        row = {
            "claim_id": cid,
            "claim": gold["claim"],
            "gold_label": gold["label"],

            "infact_clean_prediction": normalize(clean_v),
            "infact_clean_justification": clean_j or "",

            "infact_poisoned_prediction": normalize(pdump.get("pred_label")),
            "infact_poisoned_justification": pdump.get("after_justification") or "",

            "model_only_prediction": normalize(sup.get("model_only_verdict")),
            "model_only_justification": bulletize(sup.get("model_only_evidence", [])),

            "infact_assisted_merge_prediction": normalize(adump.get("assisted_pred")),
            "infact_assisted_merge_justification": "",  # never captured -- see module docstring

            "infact_subclaim_verified_prediction": normalize(
                sdump.get("subclaim_verified_pred", sdump.get("orig_pred"))),
            "infact_subclaim_verified_justification": subclaim_justification(sdump) if sdump else "",

            "gold_justification": gold.get("justification") or "",
        }
        rows.append(row)

    fieldnames = ["claim_id", "claim", "gold_label",
                 "infact_clean_prediction", "infact_clean_justification",
                 "infact_poisoned_prediction", "infact_poisoned_justification",
                 "model_only_prediction", "model_only_justification",
                 "infact_assisted_merge_prediction", "infact_assisted_merge_justification",
                 "infact_subclaim_verified_prediction", "infact_subclaim_verified_justification",
                 "gold_justification"]
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUT_CSV}")
    n_no_assisted = sum(1 for r in rows if r["infact_assisted_merge_prediction"] is None)
    print(f"  infact_assisted_merge: {len(rows) - n_no_assisted}/{len(rows)} claims have a "
         f"prediction (only ran on 5 claims); justification column is empty for ALL of them "
         f"(never captured by rejudge_assisted.py).")


if __name__ == "__main__":
    main()
