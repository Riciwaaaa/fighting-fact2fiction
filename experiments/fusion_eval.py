"""
Phase 7a: 4-system comparison for the evidence-fusion run.

Systems (canonical binary labels, gold = Supported/Refuted):
  - model_only          : model-only structured fact-check (Phase 3 verdict)
  - clean_infact        : InFact's verdict on the UN-poisoned KB (parsed from the
                          fc_results clean report; NOT necessarily gold)
  - f2f_poisoned_infact : Fact2Fiction-poisoned InFact (Phase 1/2 attacked dump)
  - fusion_defense      : the fusion judge's final verdict (Phase 6)

Reuses normalize()/compute_metrics()/parse_clean_verdict() from eval_table.py so the
metric definitions stay identical to the old runs. Emits, into the run dir:
  eval_table.md, eval_table.csv, eval_predictions.csv
plus a legacy-53 vs new-47 split (the two subsets differ systematically: the legacy
claims were selected in run 03 as clean-correct, the new ones were not).

Run under /home/ubuntu/.venv312/bin/python3.12 (needs sklearn via eval_table).
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_table import normalize, compute_metrics, parse_clean_verdict, CANON
from fusion_common import DEFAULT_RUN_DIR, REPO_ROOT, load_dev_claims, load_manifest

SYSTEMS = ["model_only", "clean_infact", "f2f_poisoned_infact", "fusion_defense"]


def read_verdict(path: Path, field: str):
    if not path.exists():
        return None
    return json.load(open(path)).get(field)


def collect_rows(run_dir: Path, fc_model: str, claim_ids: list[int], claims: list[dict]) -> dict:
    mo_dir = run_dir / "model_only"
    dumps_dir = run_dir / "attacked_infact_dumps"
    fusion_dir = run_dir / "fusion"
    clean_docs_dir = (REPO_ROOT / "Fact2Fiction" / "src" / "fc_results" / "infact"
                      / fc_model / "search_top_five" / "docs")
    rows = {}
    for cid in claim_ids:
        rows[cid] = {
            "gold": claims[cid].get("label"),
            "model_only": read_verdict(mo_dir / f"{cid}.json", "verdict"),
            "clean_infact": parse_clean_verdict(clean_docs_dir / f"{cid}"),
            "f2f_poisoned_infact": read_verdict(dumps_dir / f"{cid}.json", "pred_label"),
            "fusion_defense": read_verdict(fusion_dir / f"{cid}.json", "verdict"),
        }
    return rows


def metrics_table(rows: dict, claim_ids: list[int]) -> tuple[list[str], dict, list[int]]:
    complete = [cid for cid in claim_ids
                if rows[cid]["gold"] and all(rows[cid][s] is not None for s in SYSTEMS)]
    gold = [normalize(rows[cid]["gold"]) for cid in complete]
    table = {}
    for s in SYSTEMS:
        pred = [normalize(rows[cid][s]) for cid in complete]
        two = compute_metrics(gold, pred, ["Supported", "Refuted"])
        off_label = sum(1 for p in pred if p not in ("Supported", "Refuted"))
        table[s] = {"two": two, "off_label": off_label}
    return gold, table, complete


def render(title: str, gold: list[str], table: dict, complete: list[int]) -> str:
    lines = [f"## {title} — N={len(complete)} claims"]
    gold_dist = {c: gold.count(c) for c in ["Supported", "Refuted"]}
    lines.append(f"\nGold distribution: {gold_dist}\n")
    lines.append("| System | Accuracy | F1 Supported | F1 Refuted | Macro-F1 | Off-label preds |")
    lines.append("|---|---|---|---|---|---|")
    for s in SYSTEMS:
        m = table[s]["two"]
        lines.append(f"| {s} | {m['acc']:.3f} | {m['per_class']['Supported']:.3f} | "
                     f"{m['per_class']['Refuted']:.3f} | {m['macro']:.3f} | {table[s]['off_label']} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=str, default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--fc-model", type=str, default=None)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    manifest = load_manifest(run_dir)
    fc_model = args.fc_model or manifest["fc_model"]
    all_ids = list(manifest["claim_ids"])
    legacy_ids = list(manifest["legacy_claim_ids"])
    new_ids = list(manifest["new_claim_ids"])
    claims = load_dev_claims()

    rows = collect_rows(run_dir, fc_model, all_ids, claims)

    # Report incompleteness (tolerate missing claims rather than crashing).
    missing = {cid: [s for s in SYSTEMS if rows[cid][s] is None]
               for cid in all_ids if any(rows[cid][s] is None for s in SYSTEMS)}
    print(f"Claims in manifest: {len(all_ids)} | fully complete: "
          f"{len(all_ids) - len(missing)}")
    for cid, miss in list(missing.items())[:20]:
        print(f"  claim {cid}: missing {miss}")
    if len(missing) > 20:
        print(f"  ... and {len(missing) - 20} more incomplete claims")

    sections = []
    for title, ids in (("All claims", all_ids),
                       ("Legacy claims (dev 0-99, run-03 set)", legacy_ids),
                       ("New claims (dev 100+)", new_ids)):
        gold, table, complete = metrics_table(rows, ids)
        if complete:
            sections.append(render(title, gold, table, complete))

    md = (f"# Evidence-fusion {len(SYSTEMS)}-system comparison ({fc_model})\n\n"
          + "\n\n".join(sections) + "\n")
    print("\n" + md)

    (run_dir / "eval_table.md").write_text(md)

    # CSV: one row per system on the full set.
    gold_all, table_all, complete_all = metrics_table(rows, all_ids)
    with open(run_dir / "eval_table.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["system", "n", "accuracy", "f1_supported", "f1_refuted",
                    "macro_f1", "off_label_preds"])
        for s in SYSTEMS:
            m = table_all[s]["two"]
            w.writerow([s, len(complete_all), f"{m['acc']:.4f}",
                        f"{m['per_class']['Supported']:.4f}", f"{m['per_class']['Refuted']:.4f}",
                        f"{m['macro']:.4f}", table_all[s]["off_label"]])

    # Per-claim predictions CSV (audit).
    with open(run_dir / "eval_predictions.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["claim_id", "subset", "gold"] + SYSTEMS)
        legacy_set = set(legacy_ids)
        for cid in all_ids:
            subset = "legacy" if cid in legacy_set else "new"
            w.writerow([cid, subset, normalize(rows[cid]["gold"])]
                       + [normalize(rows[cid][s]) for s in SYSTEMS])

    print(f"\nWrote {run_dir / 'eval_table.md'}, {run_dir / 'eval_table.csv'}, "
          f"{run_dir / 'eval_predictions.csv'}")


if __name__ == "__main__":
    main()
