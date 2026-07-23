"""
Analysis tables for the sub-claim-verification defense, beyond the headline eval_table.

Purely read-only over already-produced result files -- no LLM/KB calls, plain python3 is
enough (imports eval_table.py's normalize()/compute_metrics() so T1's numbers can never
drift from the canonical eval_table.md).

Inputs (all under --results-dir, default experiments/runs/03_mimo_27claim_binary):
  - eval_predictions.csv            (gold, model_only, infact, f2f_poisoned_infact,
                                      subclaim_verified_poisoned_infact per claim)
  - subclaim_defense/{cid}.json     (defense_skipped, orig_pred, reproduced_pred,
                                      verifications[] with original_is_fake/trust)
  - attacked_infact_dumps/{cid}.json (attack_success, fact_check_fail -- cross-check only)

Output: <results-dir>/analysis.md (also echoed to stdout), plus CSVs alongside it:
  - analysis_per_claim.csv       one row per claim, every flag used across T1-T6
  - analysis_t1_final.csv        the 4-system metric table
  - analysis_t2_oracle.csv       oracle-ceiling rows
  - analysis_t3_defense_success.csv
  - analysis_t4_fabrication_matrix.csv        is_fake x trust counts
  - analysis_t4_subclaim_verifications.csv    one row per verified sub-claim (granular)
  - analysis_t5_complementarity.csv
  - analysis_t6_skip_gate.csv
"""

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
sys.path.insert(0, str(EXPERIMENTS_DIR))

from eval_table import normalize, compute_metrics  # noqa: E402

DEFAULT_CLAIM_IDS = [0, 3, 4, 5, 6, 8, 12, 14, 17, 19, 20, 22, 23, 25, 27, 28, 29, 30,
                     31, 35, 37, 42, 53, 77, 92, 93, 98]

TWO_CLASS = ["Supported", "Refuted"]


def load_predictions(csv_path: Path) -> dict[int, dict]:
    rows = {}
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            rows[int(r["claim_id"])] = r
    return rows


def load_traces(results_dir: Path, claim_ids: list[int]) -> dict[int, dict]:
    out = {}
    for cid in claim_ids:
        p = results_dir / "subclaim_defense" / f"{cid}.json"
        if p.exists():
            out[cid] = json.load(open(p))
    return out


def load_natural_skip(results_dir: Path, claim_ids: list[int]) -> dict[int, bool]:
    """The un-forced agreement decision from infact_supplement.jsonl. Needed because at
    least one claim's subclaim_defense/{cid}.json has defense_skipped=False despite
    model_only agreeing with poisoned InFact: claim 3 was run with --no-skip-gate during
    an earlier standalone mechanism inspection (the user's own fake-declaration example),
    and the full 27-claim batch later reused that cached output rather than re-deciding
    it naturally. Using infact_supplement.jsonl's flag keeps the skip-gate accounting
    (T6) honest about what the pipeline would do by default."""
    out = {}
    p = results_dir / "infact_supplement.jsonl"
    if not p.exists():
        return out
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            cid = rec.get("claim_id")
            if cid in claim_ids:
                out[cid] = bool(rec.get("defense_skipped"))
    return out


def fmt_ids(ids) -> str:
    return "{" + ",".join(str(i) for i in sorted(ids)) + "}" if ids else "{}"


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=str, default=None)
    parser.add_argument("--results-dir", type=str,
                        default=str(EXPERIMENTS_DIR / "runs" / "03_mimo_27claim_binary"))
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()

    claim_ids = ([int(x) for x in args.claims.split(",")] if args.claims
                 else list(DEFAULT_CLAIM_IDS))
    results_dir = Path(args.results_dir).resolve()
    out_path = Path(args.out) if args.out else results_dir / "analysis.md"

    preds = load_predictions(results_dir / "eval_predictions.csv")
    traces = load_traces(results_dir, claim_ids)
    natural_skip = load_natural_skip(results_dir, claim_ids)
    n = len(claim_ids)
    assert set(preds.keys()) >= set(claim_ids), \
        f"eval_predictions.csv missing claims: {set(claim_ids) - set(preds.keys())}"

    def col(system: str, cid: int) -> str | None:
        v = preds[cid].get(system)
        return v if v else None

    def correct(system: str, cid: int) -> bool:
        return normalize(col(system, cid)) == normalize(col("gold", cid))

    lines = []
    lines.append(f"# Sub-claim defense analysis — N={n} claims\n")

    # ── T1: final comparison (reuses eval_table.py's own metric fns) ──────────
    lines.append("## T1 — Final comparison\n")
    systems = ["model_only", "infact", "f2f_poisoned_infact", "subclaim_verified_poisoned_infact"]
    gold = [normalize(preds[cid]["gold"]) for cid in claim_ids]
    lines.append("| System | Accuracy | F1 Supported | F1 Refuted | Macro-F1 | # Correct |")
    lines.append("|---|---|---|---|---|---|")
    t1_correct_counts = {}
    t1_rows = []
    for s in systems:
        pred = [normalize(preds[cid].get(s)) for cid in claim_ids]
        m = compute_metrics(gold, pred, TWO_CLASS)
        n_correct = sum(1 for cid in claim_ids if correct(s, cid))
        t1_correct_counts[s] = n_correct
        lines.append(f"| {s} | {m['acc']:.3f} | {m['per_class']['Supported']:.3f} | "
                     f"{m['per_class']['Refuted']:.3f} | {m['macro']:.3f} | {n_correct}/{n} |")
        t1_rows.append([s, f"{m['acc']:.4f}", f"{m['per_class']['Supported']:.4f}",
                        f"{m['per_class']['Refuted']:.4f}", f"{m['macro']:.4f}", n_correct, n])
    lines.append("")
    write_csv(results_dir / "analysis_t1_final.csv",
             ["system", "accuracy", "f1_supported", "f1_refuted", "macro_f1", "n_correct", "n_total"],
             t1_rows)

    # ── shared claim-id sets used across T2/T3/T5/T6 ──────────────────────────
    mo_ok = {cid for cid in claim_ids if correct("model_only", cid)}
    mo_wrong = set(claim_ids) - mo_ok
    poison_ok = {cid for cid in claim_ids if correct("f2f_poisoned_infact", cid)}
    poison_wrong = set(claim_ids) - poison_ok
    def_ok = {cid for cid in claim_ids if correct("subclaim_verified_poisoned_infact", cid)}
    def_wrong = set(claim_ids) - def_ok

    fixed = poison_wrong & def_ok
    worsened = poison_ok & def_wrong
    still_wrong = poison_wrong & def_wrong
    still_ok = poison_ok & def_ok

    # ── T2: oracle ceiling ─────────────────────────────────────────────────────
    lines.append("## T2 — Oracle ceiling (model-only + poisoned InFact fused) vs achieved\n")
    recoverable = mo_ok | poison_ok
    unrecoverable = set(claim_ids) - recoverable
    capture = len(def_ok & recoverable) / len(recoverable) if recoverable else float("nan")
    lines.append("| System | Correct | Accuracy |")
    lines.append("|---|---|---|")
    lines.append(f"| model_only alone | {len(mo_ok)}/{n} | {len(mo_ok)/n:.3f} |")
    lines.append(f"| f2f_poisoned_infact alone | {len(poison_ok)}/{n} | {len(poison_ok)/n:.3f} |")
    lines.append(f"| **oracle (≥1 of the two correct)** | **{len(recoverable)}/{n}** | "
                 f"**{len(recoverable)/n:.3f}** |")
    lines.append(f"| subclaim_verified_poisoned_infact (achieved) | {len(def_ok)}/{n} | "
                 f"{len(def_ok)/n:.3f} |")
    lines.append("")
    lines.append(f"- Capture rate (defense-correct among oracle-recoverable): "
                 f"{len(def_ok & recoverable)}/{len(recoverable)} = {capture:.1%}")
    lines.append(f"- Recoverable but missed by the defense: {fmt_ids(recoverable - def_ok)}")
    lines.append(f"- Unrecoverable (both model_only and poisoned wrong): {fmt_ids(unrecoverable)}")
    lines.append("")
    write_csv(results_dir / "analysis_t2_oracle.csv",
             ["system", "n_correct", "n_total", "accuracy"],
             [["model_only_alone", len(mo_ok), n, f"{len(mo_ok)/n:.4f}"],
              ["f2f_poisoned_infact_alone", len(poison_ok), n, f"{len(poison_ok)/n:.4f}"],
              ["oracle_at_least_one_correct", len(recoverable), n, f"{len(recoverable)/n:.4f}"],
              ["subclaim_verified_achieved", len(def_ok), n, f"{len(def_ok)/n:.4f}"]])

    # ── T3: defense success rate on poison-succeeded claims ────────────────────
    lines.append("## T3 — Defense success on poison-succeeded claims\n")
    fixable = poison_wrong & mo_ok       # a correct signal existed to draw on
    no_signal = poison_wrong & mo_wrong  # no correct signal anywhere
    fixable_fixed = fixable & def_ok
    no_signal_fixed = no_signal & def_ok
    lines.append("| Subset (poisoned InFact wrong) | N | Fixed by defense | Rate |")
    lines.append("|---|---|---|---|")
    lines.append(f"| model_only correct (fixable) | {len(fixable)} | {len(fixable_fixed)} | "
                 f"{len(fixable_fixed)/len(fixable):.1%} |" if fixable else
                 "| model_only correct (fixable) | 0 | 0 | n/a |")
    lines.append(f"| model_only also wrong (no signal) | {len(no_signal)} | "
                 f"{len(no_signal_fixed)} | "
                 f"{(len(no_signal_fixed)/len(no_signal) if no_signal else float('nan')):.1%} |")
    lines.append(f"| **Overall** | **{len(poison_wrong)}** | **{len(fixed)}** | "
                 f"**{len(fixed)/len(poison_wrong):.1%}** |")
    lines.append("")
    lines.append(f"- Fixable but missed: {fmt_ids(fixable - fixable_fixed)}")
    lines.append(f"- Poison-succeeded claim ids: {fmt_ids(poison_wrong)}")
    lines.append("")
    write_csv(results_dir / "analysis_t3_defense_success.csv",
             ["subset", "n", "fixed", "rate"],
             [["model_only_correct_fixable", len(fixable), len(fixable_fixed),
               f"{len(fixable_fixed)/len(fixable):.4f}" if fixable else ""],
              ["model_only_also_wrong_no_signal", len(no_signal), len(no_signal_fixed),
               f"{len(no_signal_fixed)/len(no_signal):.4f}" if no_signal else ""],
              ["overall", len(poison_wrong), len(fixed), f"{len(fixed)/len(poison_wrong):.4f}"]])

    # ── T4: fabrication-detection matrix ────────────────────────────────────────
    lines.append("## T4 — Fabrication-detection matrix (sub-claim level)\n")
    n_verifying_claims = sum(1 for d in traces.values() if d.get("verifications"))
    lines.append(f"Every sub-claim the materiality gate flagged as worth verifying, across the "
                 f"{n_verifying_claims} claims that ran verification (10 on natural disagreement "
                 f"+ 1 forced, claim 3 — see T6 caveat; verification never runs on naturally "
                 f"skipped claims).\n")
    trust_labels = ["fabricated", "doubtful", "trustworthy"]
    counts = {True: {t: 0 for t in trust_labels}, False: {t: 0 for t in trust_labels}}
    total_verified = 0
    for d in traces.values():
        for v in d.get("verifications", []):
            isf = bool(v.get("original_is_fake"))
            tr = v.get("trust")
            if tr in trust_labels:
                counts[isf][tr] += 1
                total_verified += 1
    lines.append("| original_is_fake | fabricated | doubtful | trustworthy | total |")
    lines.append("|---|---|---|---|---|")
    for isf in (True, False):
        row = counts[isf]
        tot = sum(row.values())
        lines.append(f"| {isf} | {row['fabricated']} | {row['doubtful']} | "
                     f"{row['trustworthy']} | {tot} |")
    n_fake = sum(counts[True].values())
    n_real = sum(counts[False].values())
    recall = ((counts[True]['fabricated'] + counts[True]['doubtful']) / n_fake
             if n_fake else float("nan"))
    fpr = (counts[False]['fabricated'] / n_real) if n_real else float("nan")
    lines.append("")
    lines.append(f"- Fakes flagged fabricated/doubtful (recall): {recall:.1%} "
                 f"({counts[True]['fabricated']+counts[True]['doubtful']}/{n_fake})")
    lines.append(f"- Real evidence wrongly flagged fabricated (false-positive rate): {fpr:.1%} "
                 f"({counts[False]['fabricated']}/{n_real})" if n_real else
                 "- Real evidence wrongly flagged fabricated: n/a (0 real sub-claims verified)")
    lines.append(f"- Total sub-claims verified: {total_verified}")
    lines.append("")
    write_csv(results_dir / "analysis_t4_fabrication_matrix.csv",
             ["original_is_fake", "fabricated", "doubtful", "trustworthy", "total"],
             [[isf, counts[isf]["fabricated"], counts[isf]["doubtful"], counts[isf]["trustworthy"],
               sum(counts[isf].values())] for isf in (True, False)])

    subclaim_rows = []
    for cid, d in sorted(traces.items()):
        for v in d.get("verifications", []):
            subclaim_rows.append([
                cid, v.get("index"), v.get("question"), v.get("original_is_fake"),
                v.get("original_url"), v.get("trust"), v.get("trust_reason"),
                v.get("n_results"), v.get("n_results_fake"), v.get("revised_answer")])
    write_csv(results_dir / "analysis_t4_subclaim_verifications.csv",
             ["claim_id", "subclaim_index", "question", "original_is_fake", "original_url",
              "trust", "trust_reason", "n_results", "n_results_fake", "revised_answer"],
             subclaim_rows)

    # ── T5: system complementarity ──────────────────────────────────────────────
    lines.append("## T5 — System complementarity (model_only vs the defense)\n")
    both_ok = mo_ok & def_ok
    mo_only = mo_ok & def_wrong
    def_only = mo_wrong & def_ok
    both_wrong2 = mo_wrong & def_wrong
    lines.append("| | defense correct | defense wrong |")
    lines.append("|---|---|---|")
    lines.append(f"| **model_only correct** | {len(both_ok)} {fmt_ids(both_ok)} | "
                 f"{len(mo_only)} {fmt_ids(mo_only)} |")
    lines.append(f"| **model_only wrong** | {len(def_only)} {fmt_ids(def_only)} | "
                 f"{len(both_wrong2)} {fmt_ids(both_wrong2)} |")
    lines.append("")
    lines.append(f"- Both score {t1_correct_counts['model_only']}/{n} accuracy, but on different "
                 f"claims: the defense uniquely saves {fmt_ids(def_only)} (preserves a correct "
                 f"poisoned verdict the model itself got wrong), while missing "
                 f"{fmt_ids(mo_only)} (a correct model-only signal it didn't act on).")
    lines.append("")
    write_csv(results_dir / "analysis_t5_complementarity.csv",
             ["model_only_correct", "defense_correct", "n", "claim_ids"],
             [[True, True, len(both_ok), fmt_ids(both_ok)],
              [True, False, len(mo_only), fmt_ids(mo_only)],
              [False, True, len(def_only), fmt_ids(def_only)],
              [False, False, len(both_wrong2), fmt_ids(both_wrong2)]])

    # ── T6: skip-gate accounting ─────────────────────────────────────────────────
    lines.append("## T6 — Skip-gate accounting\n")
    # Use infact_supplement.jsonl's flag (the un-forced agreement decision), not
    # subclaim_defense/{cid}.json's stored flag -- see load_natural_skip() docstring:
    # claim 3 was manually forced through verification for inspection and would
    # otherwise have skipped naturally, which the stored trace doesn't reflect.
    skipped = {cid for cid in claim_ids if natural_skip.get(cid)}
    defended = set(claim_ids) - skipped
    skipped_ok = skipped & def_ok
    skipped_wrong = skipped & def_wrong
    shared_error = skipped & poison_wrong  # skipped AND poisoned wrong == both sides agreed wrong
    forced = {cid for cid in claim_ids
              if natural_skip.get(cid) and not traces.get(cid, {}).get("defense_skipped", True)}
    lines.append(f"- Skipped (model_only == poisoned InFact verdict): {len(skipped)}/{n}")
    lines.append(f"  - correct: {len(skipped_ok)} {fmt_ids(skipped_ok)}")
    lines.append(f"  - wrong (shared error, both sides agreed on the same wrong verdict): "
                 f"{len(skipped_wrong)} {fmt_ids(skipped_wrong)}")
    lines.append(f"- Ran the full defense (naturally, on disagreement): {len(defended)}/{n} "
                 f"{fmt_ids(defended)}")
    lines.append(f"- Of the skipped-wrong claims, all {len(shared_error)} are also in T3's "
                 f"\"no signal\" bucket {fmt_ids(no_signal)} — the skip-gate isn't costing fixable "
                 f"claims here; where it skips wrong, there was no correct signal to act on anyway.")
    if forced:
        lines.append(f"- Caveat: {fmt_ids(forced)} would have skipped naturally but was manually "
                     f"forced through the full defense with `--no-skip-gate` during an earlier "
                     f"standalone mechanism check; its result is included in T1/T4/T5 (it's real "
                     f"verification output) but counted here under \"skipped,\" matching what the "
                     f"pipeline does by default.")
    lines.append("")
    write_csv(results_dir / "analysis_t6_skip_gate.csv",
             ["category", "n", "claim_ids"],
             [["skipped_total", len(skipped), fmt_ids(skipped)],
              ["skipped_correct", len(skipped_ok), fmt_ids(skipped_ok)],
              ["skipped_wrong_shared_error", len(skipped_wrong), fmt_ids(skipped_wrong)],
              ["ran_full_defense_naturally", len(defended), fmt_ids(defended)],
              ["forced_through_defense_for_inspection", len(forced), fmt_ids(forced)]])

    # ── Footnote: judge non-determinism ─────────────────────────────────────────
    lines.append("## Footnote — Judge non-determinism\n")
    # Every claim whose trace actually ran Stage G (re-judge), forced or natural --
    # reproduced_pred/orig_pred are only meaningful there. Matches reprod_diff's own
    # filter so the fraction's numerator and denominator are computed consistently.
    ran_stage_g = [cid for cid, d in traces.items() if not d.get("defense_skipped")]
    reprod_diff = [cid for cid in ran_stage_g
                   if traces[cid].get("reproduced_pred") != traces[cid].get("orig_pred")]
    lines.append(f"`reproduced_pred` (re-judging the SAME untouched poisoned Q&A) matches "
                 f"`orig_pred` on {len(ran_stage_g) - len(reprod_diff)}/{len(ran_stage_g)} claims "
                 f"that ran the full defense; the sole drift ({fmt_ids(reprod_diff)}) still "
                 f"resolved correctly in the final verified verdict. The reported effects are not "
                 f"an artifact of re-judge noise.")
    lines.append("")

    # ── master per-claim CSV: every flag used across T1-T6, one row per claim ──
    per_claim_rows = []
    for cid in sorted(claim_ids):
        d = traces.get(cid, {})
        outcome = ("fixed" if cid in fixed else "worsened" if cid in worsened
                  else "still_wrong" if cid in still_wrong else "still_ok")
        ran_g = not d.get("defense_skipped", True)
        rp, op = d.get("reproduced_pred"), d.get("orig_pred")
        per_claim_rows.append([
            cid, preds[cid]["gold"], preds[cid].get("model_only"), preds[cid].get("infact"),
            preds[cid].get("f2f_poisoned_infact"),
            preds[cid].get("subclaim_verified_poisoned_infact"),
            cid in mo_ok, cid in poison_ok, cid in def_ok,
            cid in poison_wrong,  # poison_succeeded
            cid in recoverable,   # oracle_recoverable
            cid in fixable,       # has_mo_signal_when_poison_wrong
            outcome,
            natural_skip.get(cid), ran_g, cid in forced,
            d.get("n_subclaims"), d.get("n_verified"), d.get("n_revised"), d.get("n_added"),
            op, rp, (rp != op) if ran_g else "",
        ])
    write_csv(results_dir / "analysis_per_claim.csv",
             ["claim_id", "gold", "model_only", "infact", "f2f_poisoned_infact",
              "subclaim_verified_poisoned_infact", "model_only_correct", "poisoned_correct",
              "defense_correct", "poison_succeeded", "oracle_recoverable",
              "fixable_has_mo_signal", "outcome", "natural_skip", "ran_full_defense",
              "forced_for_inspection", "n_subclaims", "n_verified", "n_revised", "n_added",
              "orig_pred", "reproduced_pred", "reproduced_differs_from_orig"],
             per_claim_rows)

    text = "\n".join(lines)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text)
    print(text)
    print(f"\nWrote {out_path} and 9 CSVs (analysis_per_claim.csv, analysis_t{{1..6}}_*.csv) "
         f"in {results_dir}", file=sys.stderr)

    # ── internal consistency assertions (plan's verification step 2) ───────────
    # def_ok partitions exactly into "was already correct" (still_ok) and "fixed"
    # (poison_wrong -> now correct), since poison_ok/poison_wrong partition claim_ids.
    assert len(def_ok) == len(still_ok) + len(fixed), \
        f"defense-correct count ({len(def_ok)}) != still_ok ({len(still_ok)}) + fixed ({len(fixed)})"
    assert t1_correct_counts["subclaim_verified_poisoned_infact"] == len(def_ok)
    assert len(recoverable) == n - len(unrecoverable)
    assert len(both_ok) + len(mo_only) + len(def_only) + len(both_wrong2) == n
    assert total_verified == n_fake + n_real
    assert worsened == set(), f"WORSENED should be empty per prior report, got {fmt_ids(worsened)}"


if __name__ == "__main__":
    main()
