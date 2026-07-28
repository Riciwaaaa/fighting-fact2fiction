"""
TEMPORARY PROBE -- re-adjudication pass (not part of the run-05 pipeline).

Re-labels an already-completed conflict probe with the **binary** adjudicator
(`ADJUDICATE_PROMPT` v2 in tmp_conflict_probe.py) instead of the original four-label one.

Only the adjudication calls are re-run. Every model-only answer and every InFact answer is
read back from the stored JSON, so this costs one cheap call per pair and -- more importantly
-- changes nothing except the label, making the v1/v2 comparison exact rather than a
re-sampling of the whole experiment.

Why: v1's `mo_abstains` and `incomparable` rows were dropped from the denominator, and that is
where much of the signal was sitting. 94% of the abstentions were explicit denials aimed at an
assertion the poisoned fact-check had just made, and most `incomparable` rows were the
fact-checker reporting "the source does not say" against a definite answer from the reasoner.
Both are the reasoner failing to back the fact-checker -- the quantity being measured.

Handles both probe layouts:
  * conflict_probe.json    -- rows carry `side` + `infact_answer`, label field `relation`
  * controlled_conflict.json -- rows carry `clean_answer` and `poisoned_answer`, label fields
    `clean_relation` / `poisoned_relation`

Writes <prefix>_v2.json and <prefix>_v2.md. The v1 labels are preserved on every row as
`relation_v1` (etc.) so the two readings can be tabulated side by side.

Run under /home/ubuntu/.venv312/bin/python3.12.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
OUT_DIR = REPO_ROOT / "_inspect"

sys.path.insert(0, str(EXPERIMENTS_DIR))
from fusion_common import call_json, set_model  # noqa: E402
from tmp_conflict_probe import ADJUDICATE_PROMPT, _valid_adj  # noqa: E402

# (label field, InFact-answer field, reason field, display name for that side)
LAYOUTS = {
    "probe": [("relation", "infact_answer", "relation_reason", None)],
    "controlled": [("clean_relation", "clean_answer", "clean_relation_reason", "clean"),
                   ("poisoned_relation", "poisoned_answer", "poisoned_relation_reason",
                    "poisoned")],
}


def detect_layout(recs) -> str:
    keys = set(recs[0]["rows"][0])
    if "clean_answer" in keys and "poisoned_answer" in keys:
        return "controlled"
    if "infact_answer" in keys:
        return "probe"
    sys.exit(f"Unrecognised row schema: {sorted(keys)}")


def is_fake_of(row, layout):
    return row.get("is_fake") if layout == "probe" else row.get("is_fake_in_poisoned")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in-json", type=str, required=True,
                        help="e.g. _inspect/conflict_probe.json")
    parser.add_argument("--out-prefix", type=str, default=None,
                        help="default: <input stem>_v2")
    parser.add_argument("--model", type=str, default="xiaomi/mimo-v2.5-pro")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    set_model(args.model)
    in_path = Path(args.in_json)
    if not in_path.is_absolute():
        in_path = REPO_ROOT / in_path
    recs = json.load(open(in_path))
    prefix = args.out_prefix or (in_path.stem + "_v2")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    layout = detect_layout(recs)
    targets = LAYOUTS[layout]
    print(f"Layout: {layout} ({len(recs)} claims, "
          f"{sum(len(r['rows']) for r in recs)} rows x {len(targets)} side(s))", flush=True)

    # Resume: a claim already carrying v1 labels in the output file is done. The output is
    # rewritten after every claim, so an interrupted run loses at most one claim.
    out_path = OUT_DIR / f"{prefix}.json"
    done = {}
    if out_path.exists():
        for rec in json.load(open(out_path)):
            if rec["rows"] and (targets[0][0] + "_v1") in rec["rows"][0]:
                done[rec["claim_id"]] = rec
        if done:
            print(f"Resuming: {len(done)} claim(s) already re-adjudicated.", flush=True)

    for i, rec in enumerate(recs):
        if rec["claim_id"] in done:
            recs[i] = done[rec["claim_id"]]
            continue
        t0 = time.perf_counter()
        # One job per (row, side) that actually has both answers to compare.
        jobs = [(row, tgt) for row in rec["rows"] for tgt in targets
                if row.get(tgt[1]) and row.get("mo_answer")]

        def adjudicate(job):
            row, (_, ans_field, _, _) = job
            return call_json(
                ADJUDICATE_PROMPT
                .replace("[CLAIM]", rec["claim"])
                .replace("[QUESTION]", row["question"])
                .replace("[INFACT_ANSWER]", row[ans_field])
                .replace("[MO_ANSWER]", row["mo_answer"]),
                _valid_adj)

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            results = list(ex.map(adjudicate, jobs))

        # Preserve v1 before overwriting, then write v2 in place.
        for row in rec["rows"]:
            for rel_f, _, rsn_f, _ in targets:
                row[rel_f + "_v1"] = row.get(rel_f)
                row[rsn_f + "_v1"] = row.get(rsn_f)
                row[rel_f] = None
                row[rsn_f] = None
        for (row, (rel_f, _, rsn_f, _)), adj in zip(jobs, results):
            row[rel_f] = (adj or {}).get("relation")
            row[rsn_f] = (adj or {}).get("reason")

        parts = []
        for rel_f, _, _, display in targets:
            sub = [r for r in rec["rows"] if r.get(rel_f)]
            k = sum(1 for r in sub if r[rel_f] == "conflict")
            parts.append(f"{display or 'conflict'} {k}/{len(sub)}")
        print(f"[{rec['claim_id']}] " + " | ".join(parts) +
              f" ({time.perf_counter()-t0:.0f}s)", flush=True)
        with open(OUT_DIR / f"{prefix}.json", "w") as f:
            json.dump(recs, f, indent=2)

    # ---------------------------------------------------------------- report
    def collect(subset, rel_f, display):
        out = []
        for rec in subset:
            for r in rec["rows"]:
                if not r.get(rel_f):
                    continue
                if layout == "probe" and r.get("side") != display:
                    continue
                out.append(r)
        return out

    sides = ["clean", "poisoned"]
    field_of = {("probe", "clean"): "relation", ("probe", "poisoned"): "relation",
                ("controlled", "clean"): "clean_relation",
                ("controlled", "poisoned"): "poisoned_relation"}

    def stats(subset, side, version=""):
        rel_f = field_of[(layout, side)] + version
        rows = collect(subset, rel_f, side)
        k = sum(1 for r in rows if r[rel_f] == "conflict")
        return len(rows), k, (k / len(rows) if rows else float("nan"))

    flip = [r for r in recs if r.get("attack_flipped")]
    noflip = [r for r in recs if not r.get("attack_flipped")]

    L = [f"# Binary re-adjudication of `{in_path.name}`", "",
         "Same claims, same questions, same model-only answers, same InFact answers as the "
         "original run -- **only the adjudicator changed**. It now has exactly two labels, "
         "`agree` and `conflict`, and no way to set a pair aside. Every pair is in the "
         "denominator.", "",
         "The two labels v1 used to park rows in -- `mo_abstains` and `incomparable` -- were "
         "excluded from v1's denominator. That is where much of the signal was: 94% of the "
         "abstentions were explicit denials of an assertion the fact-check had just made, and "
         "most `incomparable` rows were the fact-checker saying \"the source does not say\" "
         "against a definite answer from the reasoner.", "",
         f"Sample: **{len(recs)} claims**, {sum(len(r['rows']) for r in recs)} questions.", "",
         "---", "", "## Headline -- v2 (binary)", "",
         "| condition | pairs | conflicts | **conflict rate** |", "|---|---|---|---|"]
    for name, subset in [("ALL claims", recs), ("attack FLIPPED", flip),
                         ("attack did NOT flip", noflip)]:
        if not subset:
            continue
        for side in sides:
            n, k, rate = stats(subset, side)
            L.append(f"| {name} -- vs **{side}** | {n} | {k} | **{rate:.1%}** |")

    nc, kc, rc = stats(recs, "clean")
    npo, kp, rp = stats(recs, "poisoned")
    L += ["", f"**Poisoned minus clean: {rp - rc:+.1%}** ({rp:.1%} vs {rc:.1%}).", ""]

    L += ["## Three readings of the same data, side by side", "",
          "1. **v1 strict** -- the original four-label run, `mo_abstains`/`incomparable` dropped "
          "from the denominator.",
          "2. **v1 broad** -- same labels, but every `mo_abstains` and `incomparable` row "
          "counted as a conflict. This is the blunt version of the binary idea: any row where "
          "the reasoner did not positively back the fact-checker is a conflict.",
          "3. **v2 binary** -- re-adjudicated with the two-label prompt, which decides by "
          "*direction*: a report of non-recall conflicts with \"X is established\" but agrees "
          "with \"X is unevidenced/fabricated\".", "",
          "| condition | v1 strict | v1 broad | v2 binary |", "|---|---|---|---|"]
    readings = {}
    for side in sides:
        rel_f1 = field_of[(layout, side)] + "_v1"
        v1rows = collect(recs, rel_f1, side)
        comp = [r for r in v1rows if r[rel_f1] in ("agree", "conflict")]
        k_strict = sum(1 for r in comp if r[rel_f1] == "conflict")
        r_strict = k_strict / len(comp) if comp else float("nan")
        k_broad = sum(1 for r in v1rows if r[rel_f1] != "agree")
        r_broad = k_broad / len(v1rows) if v1rows else float("nan")
        n2, k2, r2 = stats(recs, side)
        readings[side] = (r_strict, r_broad, r2)
        L.append(f"| vs **{side}** | {k_strict}/{len(comp)} = **{r_strict:.1%}** | "
                 f"{k_broad}/{len(v1rows)} = **{r_broad:.1%}** | "
                 f"{k2}/{n2} = **{r2:.1%}** |")
    L += ["", "| reading | poisoned - clean | ratio |", "|---|---|---|"]
    for i, nm in enumerate(("v1 strict", "v1 broad", "v2 binary")):
        c, p = readings["clean"][i], readings["poisoned"][i]
        L.append(f"| {nm} | {p - c:+.1%} | {p / c:.1f}x |" if c else
                 f"| {nm} | {p - c:+.1%} | n/a |")
    L += ["", "The reading to prefer is the one that separates a poisoned fact-check from a "
          "clean one by the widest margin, since that is the quantity the defense would key "
          "off.", ""]

    L += ["", "### Where the v1 buckets ended up in v2", "",
          "| v1 label | -> v2 `agree` | -> v2 `conflict` |", "|---|---|---|"]
    for v1lab in ("agree", "conflict", "mo_abstains", "incomparable"):
        a = c = 0
        for side in sides:
            rel_f = field_of[(layout, side)]
            for r in collect(recs, rel_f, side):
                if r.get(rel_f + "_v1") == v1lab:
                    if r[rel_f] == "agree":
                        a += 1
                    elif r[rel_f] == "conflict":
                        c += 1
        L.append(f"| `{v1lab}` | {a} | {c} |")

    # planted vs authentic, poisoned side only
    rel_f = field_of[(layout, "poisoned")]
    prows = collect(recs, rel_f, "poisoned")
    fk = [r for r in prows if is_fake_of(r, layout)]
    au = [r for r in prows if not is_fake_of(r, layout)]
    L += ["", "---", "", "## Within the poisoned run: planted vs authentic evidence", "",
          "`is_fake` is withheld from every prompt and used only here.", "",
          "| InFact evidence | pairs | conflicts | conflict rate |", "|---|---|---|---|"]
    for nm, s in [("planted (is_fake=True)", fk), ("authentic (is_fake=False)", au)]:
        k = sum(1 for r in s if r[rel_f] == "conflict")
        L.append(f"| {nm} | {len(s)} | {k} | **{k/len(s):.1%}** |" if s
                 else f"| {nm} | 0 | 0 | n/a |")
    if fk and au:
        kf = sum(1 for r in fk if r[rel_f] == "conflict") / len(fk)
        ka = sum(1 for r in au if r[rel_f] == "conflict") / len(au)
        L += ["", f"Separation: **{kf / ka:.1f}x**." if ka else
              "Separation: authentic evidence produced no conflicts at all."]

    L += ["", "---", "", "## Per claim", "",
          "| claim | gold | clean | poisoned | flipped | vs clean | vs poisoned |",
          "|---|---|---|---|---|---|---|"]
    for rec in recs:
        cells = []
        for side in sides:
            n, k, rate = stats([rec], side)
            cells.append(f"{k}/{n}" + (f" ({rate:.0%})" if n else ""))
        L.append(f"| {rec['claim_id']} | {rec.get('gold_label')} | {rec.get('clean_verdict')} | "
                 f"{rec.get('poisoned_verdict')} | "
                 f"{'yes' if rec.get('attack_flipped') else 'no'} | " + " | ".join(cells) + " |")

    # Rows v1 parked and v2 now counts as conflict -- the recovered signal.
    L += ["", "---", "", "## Recovered rows: v1 parked them, v2 calls them `conflict`", "",
          "These are the pairs the four-label adjudicator dropped from the denominator.", ""]
    rel_f = field_of[(layout, "poisoned")]
    rsn_f = rel_f.replace("relation", "relation_reason")
    ans_f = "infact_answer" if layout == "probe" else "poisoned_answer"
    shown = 0
    for rec in recs:
        for r in rec["rows"]:
            if shown >= 15:
                break
            if layout == "probe" and r.get("side") != "poisoned":
                continue
            if (r.get(rel_f) == "conflict"
                    and r.get(rel_f + "_v1") in ("mo_abstains", "incomparable")):
                tag = "planted" if is_fake_of(r, layout) else "authentic"
                L += [f"**claim {rec['claim_id']}** -- {tag} -- v1: `{r[rel_f + '_v1']}`", "",
                      f"*Q:* {r['question']}", "",
                      f"*InFact (poisoned):* {(r.get(ans_f) or '')[:400]}", "",
                      f"*model-only:* {(r.get('mo_answer') or '')[:400]}", "",
                      f"*v2 adjudicator:* {r.get(rsn_f)}", "", "---", ""]
                shown += 1

    (OUT_DIR / f"{prefix}.md").write_text("\n".join(L))
    print(f"\nv2: clean {rc:.1%} vs poisoned {rp:.1%} (lift {rp-rc:+.1%})")
    print(f"Wrote {OUT_DIR / (prefix + '.md')}")


if __name__ == "__main__":
    main()
