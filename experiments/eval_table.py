"""
Part 4: 4-system comparison table (Accuracy, Per-class F1, Macro-F1).

Systems:
  - model_only                          : model-only fact-check (xiaomi/mimo-v2.5-pro)
  - infact                              : clean (non-poisoned) InFact  [== gold by construction]
  - f2f_poisoned_infact                 : Fact2Fiction-poisoned InFact
  - model_only_assisted_poisoned_infact : poisoned InFact re-judged after additive merge of
                                          model-guided evidence retrieved from the poisoned KB

Gold labels on the attack set are only Supported/Refuted, so the primary metrics are computed
over those two classes (off-label predictions like NEI/Conflicting simply count as wrong). A
full 4-class view is also emitted.

Run under /home/ubuntu/.venv312/bin/python3.12 (needs sklearn).
"""

import argparse
import csv
import json
import re
from pathlib import Path

from sklearn.metrics import accuracy_score, f1_score

REPO_ROOT = Path(__file__).resolve().parent.parent
DEV_JSON = REPO_ROOT / "DEFAME" / "data" / "AVeriTeC" / "dev.json"

CANON = ["Supported", "Refuted", "Not Enough Evidence", "Conflicting Evidence/Cherrypicking"]

DEFAULT_CLAIM_IDS = [0, 3, 4, 5, 6, 8, 12, 14, 17, 19, 20, 22, 23, 25, 27, 28, 29, 30,
                     31, 35, 37, 42, 53, 77, 92, 93, 98]

SYSTEMS = ["model_only", "infact", "f2f_poisoned_infact", "model_only_assisted_poisoned_infact",
           "subclaim_verified_poisoned_infact"]


def normalize(label) -> str | None:
    """Map any label dialect (canonical / InFact .value / enum NAME) to the canonical space."""
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
    return None  # e.g. "error: refused to answer" -> unknown (counts as wrong)


def parse_clean_verdict(report_path: Path) -> str | None:
    if not report_path.exists():
        return None
    text = report_path.read_text()
    m = re.search(r"###\s*Verdict:\s*([^\n#]+)", text)
    return m.group(1).strip() if m else None


def load_jsonl_field(path: Path, field: str) -> dict:
    out = {}
    if not path.exists():
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            out[rec["claim_id"]] = rec.get(field)
    return out


def compute_metrics(gold: list[str], pred: list[str], labels: list[str]) -> dict:
    """Accuracy over all + per-class F1 + macro-F1 over `labels`. `pred` may contain None."""
    pred_s = [p if p is not None else "UNKNOWN" for p in pred]
    acc = accuracy_score(gold, pred_s)
    per = f1_score(gold, pred_s, labels=labels, average=None, zero_division=0)
    macro = f1_score(gold, pred_s, labels=labels, average="macro", zero_division=0)
    return {"acc": acc, "per_class": dict(zip(labels, per)), "macro": macro}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=str, default=None)
    parser.add_argument("--results-dir", type=str,
                        default=str(REPO_ROOT / "experiments" / "runs" / "02_mimo_27claim_4class"))
    parser.add_argument("--fc-model", type=str, default="mimo_v25_pro")
    parser.add_argument("--skip-systems", type=str, default=None,
                        help="Comma-separated system names to drop from the table and from "
                             "the completeness requirement (e.g. a system only run on a subset)")
    args = parser.parse_args()

    if args.skip_systems:
        drop = set(args.skip_systems.split(","))
        SYSTEMS[:] = [s for s in SYSTEMS if s not in drop]

    claim_ids = ([int(x) for x in args.claims.split(",")] if args.claims
                 else list(DEFAULT_CLAIM_IDS))

    results_dir = Path(args.results_dir).resolve()
    supplement_jsonl = results_dir / "infact_supplement.jsonl"
    dumps_dir = results_dir / "attacked_infact_dumps"
    assisted_dir = results_dir / "assisted_reverdict"
    subclaim_dir = results_dir / "subclaim_defense"
    clean_docs_dir = REPO_ROOT / "Fact2Fiction" / "src" / "fc_results" / "infact" / args.fc_model / "search_top_five" / "docs"

    with open(DEV_JSON) as f:
        claims = json.load(f)

    model_only = load_jsonl_field(supplement_jsonl, "model_only_verdict")

    # Assemble raw (un-normalized) predictions per claim.
    rows = {}
    for cid in claim_ids:
        gold = claims[cid].get("label")
        dump = dumps_dir / f"{cid}.json"
        poisoned = json.load(open(dump)).get("pred_label") if dump.exists() else None
        assisted_p = assisted_dir / f"{cid}.json"
        assisted = json.load(open(assisted_p)).get("assisted_pred") if assisted_p.exists() else None
        subclaim_p = subclaim_dir / f"{cid}.json"
        subclaim = (json.load(open(subclaim_p)).get("subclaim_verified_pred")
                    if subclaim_p.exists() else None)
        clean = parse_clean_verdict(clean_docs_dir / f"{cid}")
        rows[cid] = {
            "gold": gold,
            "model_only": model_only.get(cid),
            "infact": clean,
            "f2f_poisoned_infact": poisoned,
            "model_only_assisted_poisoned_infact": assisted,
            "subclaim_verified_poisoned_infact": subclaim,
        }

    # Common set: claims where gold + all 4 systems have a prediction.
    complete = [cid for cid in claim_ids
                if rows[cid]["gold"] and all(rows[cid][s] is not None for s in SYSTEMS)]
    missing = {cid: [s for s in SYSTEMS if rows[cid][s] is None] for cid in claim_ids
               if cid not in complete}

    print(f"Claims requested: {len(claim_ids)} | complete (all systems present): {len(complete)}")
    if missing:
        print("Incomplete claims (skipped from the table):")
        for cid, miss in missing.items():
            print(f"  claim {cid}: missing {miss or ['gold']}")

    gold = [normalize(rows[cid]["gold"]) for cid in complete]

    # Per-system metrics over the common set.
    table = {}
    for s in SYSTEMS:
        pred = [normalize(rows[cid][s]) for cid in complete]
        two = compute_metrics(gold, pred, ["Supported", "Refuted"])
        four = compute_metrics(gold, pred, CANON)
        off_label = sum(1 for p in pred if p in ("Not Enough Evidence",
                                                 "Conflicting Evidence/Cherrypicking", None))
        table[s] = {"two": two, "four": four, "off_label": off_label}

    # ---- Render primary (2-class) markdown table ----
    lines = []
    lines.append(f"# {len(SYSTEMS)}-system comparison (mimo, poisoned-KB defense) — N={len(complete)} claims")
    gold_dist = {c: gold.count(c) for c in ["Supported", "Refuted"]}
    lines.append(f"\nGold distribution: {gold_dist}\n")
    lines.append("## Primary metrics (2 gold classes: Supported, Refuted)\n")
    lines.append("| System | Accuracy | F1 Supported | F1 Refuted | Macro-F1 | Off-label preds |")
    lines.append("|---|---|---|---|---|---|")
    for s in SYSTEMS:
        m = table[s]["two"]
        lines.append(f"| {s} | {m['acc']:.3f} | {m['per_class']['Supported']:.3f} | "
                     f"{m['per_class']['Refuted']:.3f} | {m['macro']:.3f} | {table[s]['off_label']} |")

    lines.append("\n## Full 4-class view\n")
    lines.append("| System | Accuracy | F1 Sup | F1 Ref | F1 NEI | F1 Conf | Macro-F1 |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in SYSTEMS:
        m = table[s]["four"]
        pc = m["per_class"]
        lines.append(f"| {s} | {m['acc']:.3f} | {pc['Supported']:.3f} | {pc['Refuted']:.3f} | "
                     f"{pc['Not Enough Evidence']:.3f} | {pc['Conflicting Evidence/Cherrypicking']:.3f} | "
                     f"{m['macro']:.3f} |")

    md = "\n".join(lines)
    print("\n" + md)

    out_md = results_dir / "eval_table.md"
    out_md.write_text(md + "\n")

    # ---- CSV (tidy: one row per system, primary metrics) ----
    out_csv = results_dir / "eval_table.csv"
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["system", "n", "accuracy", "f1_supported", "f1_refuted",
                    "macro_f1_2class", "off_label_preds"])
        for s in SYSTEMS:
            m = table[s]["two"]
            w.writerow([s, len(complete), f"{m['acc']:.4f}", f"{m['per_class']['Supported']:.4f}",
                        f"{m['per_class']['Refuted']:.4f}", f"{m['macro']:.4f}", table[s]["off_label"]])

    # ---- Per-claim predictions CSV (audit) ----
    out_pred = results_dir / "eval_predictions.csv"
    with open(out_pred, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["claim_id", "gold"] + SYSTEMS)
        for cid in claim_ids:
            w.writerow([cid, normalize(rows[cid]["gold"])]
                       + [normalize(rows[cid][s]) for s in SYSTEMS])

    print(f"\nWrote {out_md}, {out_csv}, {out_pred}")


if __name__ == "__main__":
    main()
