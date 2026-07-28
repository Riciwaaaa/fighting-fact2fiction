# Experiment runs

Chronological phases of the model-only-vs-poisoned-InFact defense work. Each directory is the
output of a pipeline stage in `experiments/*.py`; scripts default their `--results-dir`/`--out` to
the directory listed below, overridable on the command line.

## 05_mimo_100claim_fusion/ — current

100-claim AVeriTeC-binary set, fact-checker `xiaomi/mimo-v2.5-pro`, attacker `deepseek_v4_flash`.
Replaces 03/'s asymmetric defense with a **symmetric evidence-fusion** pipeline and doubles the
claim set. Two things changed conceptually:

- **Claim set** = 03/'s 53 claims + 47 more binary claims taken in dev order from id 100
  (`make_claim_manifest.py` → `claims.json`, the single source of truth; no script hardcodes ids).
  The old "InFact answered it correctly before the attack" eligibility filter is **gone**, so
  `clean_infact` no longer equals gold by construction — it is simply InFact's verdict on the
  un-poisoned KB, whatever that verdict is.
- **Defense** = both fact-checks are treated symmetrically. The retrieval fact-checker and the
  knowledge-only reasoner each produce sub-claims/Q&A with worded evidence statements; every
  evidence item from *either* side gets corroboration-probing verification queries run against the
  poisoned KB, then a per-item confidence rating, and a single fusion judge issues the final
  verdict. There is no InFact re-judge and no agreement skip-gate.

Pipeline (each script takes `--run-dir`, reads `claims.json`, and skips claims already done):

```
make_claim_manifest.py  → claims.json
build_kb_index.py       → extends DEFAME's KB kNN index to the new claims (dev ships resources
                          for all 500 but a prebuilt index for only 0-99)
run_clean_infact.py     → Fact2Fiction/src/fc_results/.../docs/{cid}   (clean InFact, binary)
run_attacked_infact.py  → attacked_infact_dumps/{cid}.json             (poisoned InFact)
fusion_model_only.py    → model_only/{cid}.json      (structured sub-claims + memory evidence)
fusion_evidence_pool.py → evidence_pool/{cid}.json   (both sides' evidence + probing retrieval)
fusion_confidence.py    → confidence/{cid}.json      (per-evidence confidence + commentary)
fusion_judge.py         → fusion/{cid}.json          (final fused verdict)
fusion_eval.py          → eval_table.{md,csv}, eval_predictions.csv
fusion_analyze.py       → analysis.md + analysis_*.csv
```

Systems compared: `model_only` · `clean_infact` · `f2f_poisoned_infact` · `fusion_defense`.

**No oracle.** 03/'s `TRUST_PROMPT` told the model that a `/created` URL is planted — that is the
attack's own marker, so the defense was partly reading the answer key. No prompt here mentions URL
patterns; `is_fake` is recorded in the outputs but only ever consumed by `fusion_analyze.py`, as
held-out ground truth for calibration tables.

Operational notes (this box is 4-core / 7 GB): everything KB-related must run under
`/home/ubuntu/.venv312/bin/python3.12`, one heavy process at a time. Embedding is the bottleneck —
`sentence-transformers` pads each batch to its longest member, so `build_kb_index.py` and
`poisoned_kb.py` embed in bounded slices at `batch_size=4`; a larger batch peaks at ~3.5 GB on a
resource-heavy claim and gets OOM-killed. `build_kb_index.py` writes the shared index atomically.

## 03_mimo_27claim_binary/ — superseded by 05/

AVeriTeC-binary subset (`Supported`/`Refuted` only — see `experiments/make_binary_averitec.py`
and `DEFAME/data/AVeriTeC/dev_binary.json`), fact-checker `xiaomi/mimo-v2.5-pro`, attacker
`deepseek_v4_flash`. **The directory name is stale: this run has 53 claims, not 27** — the binary
claims among dev ids 0-99 that InFact answered correctly pre-attack. Produced by, in order:
`run_attacked_infact.py --binary` → `attacked_infact_dumps/`
`infact_supplement.py --binary` → `infact_supplement.jsonl` (model-only verdict + gap detection)
`subclaim_defense.py --binary` → `subclaim_defense/` (the working defense: sub-claim alignment,
  materiality gating, fabrication verification against the poisoned KB, targeted re-judge)
`eval_table.py` → `eval_table.md`/`.csv` (4-system comparison)
`analyze_defense.py` → `analysis.md` + `analysis_*.csv` (oracle ceiling, defense success rate,
  fabrication-detection matrix, model/defense complementarity, skip-gate accounting)

Also has `assisted_reverdict/` (5 claims only) — the earlier, abandoned document-level
additive-merge defense, kept for comparison; see 02/ for its full run.

**Read `analysis.md` first** for the actual findings.

## 02_mimo_27claim_4class/ — superseded

Same 27 claims, same models, but *before* the binary restriction — the fact-checker could still
output NEI/Conflicting. Defense here is the document-level additive-merge approach
(`rejudge_assisted.py`, `assisted_reverdict/`): retrieve extra evidence from the poisoned KB and
bulk-merge it into the document before re-judging. Superseded by 03/'s sub-claim approach after
this showed no accuracy improvement over the poisoned baseline.

## 01_deepseek_10claim/ — earliest, superseded

First 10-claim pass, fact-checker `deepseek/deepseek-v4-pro`, single-call model-only baseline
(`evidence_rag_probe.py`) with clean-KB grounding retrieval. Predates the gap-detection /
poisoned-KB / sub-claim machinery entirely.

## 04_results_baseline_100claim/ — pre-existing baseline comparison

Output of `combine_results.py`: merges each model's original (pre-attack) InFact predictions from
`DEFAME/out/...` with post-attack predictions from `Fact2Fiction/src/attack/attack_results/...`
into one `combined_results_{model}_100.csv` per model, over the full 100-claim set (4-class:
Supported/Refuted/NEI/Conflicting). Independent of the 01-03 pipeline above — a separate,
earlier baseline comparison across `deepseek_v4_flash`/`mimo_v25_pro`/`minimax_m3`/`gemini_3.5_flash`.
