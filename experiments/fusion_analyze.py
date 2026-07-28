"""
Phase 7b: analysis of the evidence-fusion defense.

Self-contained (stdlib only; no sklearn, no openai) so it runs under plain python3.
Reads the run's per-claim JSON outputs and the claim manifest, and writes:

  analysis.md
  analysis_defense.csv        per-claim defense outcome vs the poisoned attack
  analysis_confidence.csv     per-evidence confidence vs the withheld is_fake oracle

Tables:
  T1 Defense success   : on claims where the attack flipped InFact off gold, did the
                         fusion judge recover the gold verdict? Any regressions (fusion
                         wrong where poisoned InFact was right)?
  T2 Confidence calib  : mean fusion-assigned confidence for fake-backed vs authentic
                         InFact evidence (the ONE place is_fake is legitimately used --
                         as held-out ground truth, never fed to a prompt).
  T3 Corroboration     : distribution of the corroboration label by is_fake.
  T4 Agreement matrix  : how often each pair of the 4 systems agrees.
"""

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEV_JSON = REPO_ROOT / "DEFAME" / "data" / "AVeriTeC" / "dev.json"
DEFAULT_RUN_DIR = REPO_ROOT / "experiments" / "runs" / "05_mimo_100claim_fusion"
SYSTEMS = ["model_only", "clean_infact", "f2f_poisoned_infact", "fusion_defense"]


def canon(label):
    if label is None:
        return None
    s = str(label).strip().lower()
    if s in ("supported", "support"):
        return "Supported"
    if s in ("refuted", "refute"):
        return "Refuted"
    if "conflict" in s or "cherry" in s:
        return "Conflicting"
    if "not enough" in s or s == "nei":
        return "NEI"
    return s or None


def parse_clean_verdict(path: Path):
    import re
    if not path.exists():
        return None
    m = re.search(r"###\s*Verdict:\s*([^\n#]+)", path.read_text())
    return m.group(1).strip() if m else None


def read_field(path: Path, field: str):
    if not path.exists():
        return None
    return json.load(open(path)).get(field)


def mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else float("nan")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=str, default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--fc-model", type=str, default=None)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    manifest = json.load(open(run_dir / "claims.json"))
    fc_model = args.fc_model or manifest["fc_model"]
    all_ids = list(manifest["claim_ids"])
    legacy_set = set(manifest["legacy_claim_ids"])
    dev = json.load(open(DEV_JSON))

    mo_dir = run_dir / "model_only"
    dumps_dir = run_dir / "attacked_infact_dumps"
    fusion_dir = run_dir / "fusion"
    conf_dir = run_dir / "confidence"
    clean_docs_dir = (REPO_ROOT / "Fact2Fiction" / "src" / "fc_results" / "infact"
                      / fc_model / "search_top_five" / "docs")

    rows = {}
    for cid in all_ids:
        rows[cid] = {
            "gold": canon(dev[cid].get("label")),
            "model_only": canon(read_field(mo_dir / f"{cid}.json", "verdict")),
            "clean_infact": canon(parse_clean_verdict(clean_docs_dir / f"{cid}")),
            "f2f_poisoned_infact": canon(read_field(dumps_dir / f"{cid}.json", "pred_label")),
            "fusion_defense": canon(read_field(fusion_dir / f"{cid}.json", "verdict")),
        }

    complete = [cid for cid in all_ids
                if rows[cid]["gold"] and all(rows[cid][s] is not None for s in SYSTEMS)]

    # ── T1: defense success on attack-flipped claims ────────────────────────────
    attacked = [cid for cid in complete
                if rows[cid]["f2f_poisoned_infact"] != rows[cid]["gold"]]
    recovered = [cid for cid in attacked if rows[cid]["fusion_defense"] == rows[cid]["gold"]]
    # Regression: poisoned InFact was right but the fusion defense broke it.
    poisoned_right = [cid for cid in complete
                      if rows[cid]["f2f_poisoned_infact"] == rows[cid]["gold"]]
    regressions = [cid for cid in poisoned_right
                   if rows[cid]["fusion_defense"] != rows[cid]["gold"]]

    defense_csv = run_dir / "analysis_defense.csv"
    with open(defense_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["claim_id", "subset", "gold"] + SYSTEMS
                   + ["attack_flipped", "recovered", "regression"])
        for cid in complete:
            r = rows[cid]
            flipped = r["f2f_poisoned_infact"] != r["gold"]
            w.writerow([cid, "legacy" if cid in legacy_set else "new", r["gold"]]
                       + [r[s] for s in SYSTEMS]
                       + [flipped,
                          flipped and r["fusion_defense"] == r["gold"],
                          (not flipped) and r["fusion_defense"] != r["gold"]])

    # ── T2/T3: confidence calibration vs the withheld is_fake oracle ────────────
    conf_by_fake = defaultdict(list)   # is_fake -> [confidence]
    corrob_by_fake = defaultdict(Counter)
    conf_rows = []
    for cid in all_ids:
        cpath = conf_dir / f"{cid}.json"
        if not cpath.exists():
            continue
        for it in json.load(open(cpath)).get("evidence", []):
            if it.get("side") != "infact":
                continue  # is_fake ground truth only exists for retrieved InFact evidence
            is_fake = bool(it.get("is_fake"))
            conf = it.get("confidence")
            conf_by_fake[is_fake].append(conf)
            corrob_by_fake[is_fake][it.get("corroboration")] += 1
            conf_rows.append([cid, it.get("id"), is_fake, conf,
                              it.get("corroboration")])

    conf_csv = run_dir / "analysis_confidence.csv"
    with open(conf_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["claim_id", "evidence_id", "is_fake", "confidence", "corroboration"])
        w.writerows(conf_rows)

    # ── T4: pairwise agreement matrix ───────────────────────────────────────────
    agree = {}
    for a in SYSTEMS:
        for b in SYSTEMS:
            agree[(a, b)] = sum(1 for cid in complete if rows[cid][a] == rows[cid][b])

    # ── Render ──────────────────────────────────────────────────────────────────
    L = []
    L.append(f"# Evidence-fusion defense analysis ({fc_model})\n")
    L.append(f"Complete claims (gold + all 4 systems present): **{len(complete)}** "
             f"of {len(all_ids)}.\n")

    L.append("## T1 — Defense success (attack-flipped claims)\n")
    L.append(f"- Claims the attack flipped off gold: **{len(attacked)}**")
    L.append(f"- Of those, recovered by the fusion defense: **{len(recovered)}** "
             f"({100 * len(recovered) / len(attacked):.0f}%)" if attacked else
             "- Of those, recovered: n/a (no flipped claims)")
    L.append(f"- Regressions (poisoned InFact right, fusion wrong): **{len(regressions)}** "
             f"{regressions if regressions else ''}\n")

    def acc(system):
        c = [cid for cid in complete if rows[cid][system] == rows[cid]["gold"]]
        return len(c) / len(complete) if complete else float("nan")
    L.append("Per-system accuracy on the complete set:\n")
    L.append("| System | Accuracy |")
    L.append("|---|---|")
    for s in SYSTEMS:
        L.append(f"| {s} | {acc(s):.3f} |")
    L.append("")

    L.append("## T2 — Confidence calibration vs held-out is_fake\n")
    L.append("Mean fusion-assigned confidence for retrieved InFact evidence, split by whether "
             "the evidence was actually planted by the attack (is_fake). is_fake is NEVER shown "
             "to any prompt; it is used here only as held-out ground truth.\n")
    L.append("| InFact evidence | N | Mean confidence |")
    L.append("|---|---|---|")
    L.append(f"| authentic (is_fake=False) | {len(conf_by_fake[False])} | "
             f"{mean(conf_by_fake[False]):.3f} |")
    L.append(f"| planted (is_fake=True) | {len(conf_by_fake[True])} | "
             f"{mean(conf_by_fake[True]):.3f} |\n")

    L.append("## T3 — Corroboration label vs held-out is_fake\n")
    labels = ["corroborated", "uncorroborated", "contradicted", None]
    L.append("| InFact evidence | " + " | ".join(str(x) for x in labels) + " |")
    L.append("|---|" + "|".join("---" for _ in labels) + "|")
    for fake in (False, True):
        cells = " | ".join(str(corrob_by_fake[fake].get(x, 0)) for x in labels)
        L.append(f"| is_fake={fake} | {cells} |")
    L.append("")

    L.append("## T4 — Pairwise system agreement (of "
             f"{len(complete)} complete claims)\n")
    L.append("| | " + " | ".join(SYSTEMS) + " |")
    L.append("|---|" + "|".join("---" for _ in SYSTEMS) + "|")
    for a in SYSTEMS:
        cells = " | ".join(str(agree[(a, b)]) for b in SYSTEMS)
        L.append(f"| {a} | {cells} |")
    L.append("")

    md = "\n".join(L) + "\n"
    (run_dir / "analysis.md").write_text(md)
    print(md)
    print(f"Wrote {run_dir / 'analysis.md'}, {defense_csv}, {conf_csv}")


if __name__ == "__main__":
    main()
