# Experiment runs

Chronological phases of the model-only-vs-poisoned-InFact defense work. Each directory is the
output of a pipeline stage in `experiments/*.py`; scripts default their `--results-dir`/`--out` to
the directory listed below, overridable on the command line.

## 03_mimo_27claim_binary/ — current, final

27-claim AVeriTeC-binary subset (`Supported`/`Refuted` only — see `experiments/make_binary_averitec.py`
and `DEFAME/data/AVeriTeC/dev_binary.json`), fact-checker `xiaomi/mimo-v2.5-pro`, attacker
`deepseek_v4_flash`. Produced by, in order:
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
