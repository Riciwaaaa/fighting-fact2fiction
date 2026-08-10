# Experiment runs

Chronological phases of the model-only-vs-poisoned-InFact defense work. Each directory is the
output of a pipeline stage in `experiments/*.py`; scripts default their `--results-dir`/`--out` to
the directory listed below, overridable on the command line.

> **Start at [`16_binary100_pr008_fix12/`](16_binary100_pr008_fix12/)** — the current headline
> result (`final/report.md`, `final/metrics.csv`). 14/ and 15/ are its ablation arms.

## 16_binary100_pr008_fix12/ — current result

The **first 100 binary claims in AVeriTeC dev order** (77 gold-Refuted / 23 gold-Supported),
poison rate 0.08. Four arms on one claim set: `C` clean retrieval, `P` poisoned retrieval, `P+M`
poisoned merged with model-only memory, `M` memory alone.

| arm | accuracy | Supported F1 | Refuted F1 | macro-F1 |
|---|---|---|---|---|
| C  clean retrieval | 86.0% | 0.650 | 0.912 | 0.781 |
| M  memory alone | 85.0% | 0.545 | 0.916 | 0.731 |
| **P+M merged** | **82.0%** | 0.571 | 0.886 | **0.729** |
| P  poisoned baseline | 66.0% | 0.370 | 0.767 | 0.569 |

Split by whether the attack actually landed — 71 claims have a poisoned corpus, 29 do not and are
backfilled (`P` = `C`, `P+M` = `CM`, since an unattacked claim's poisoned KB is byte-identical to
the clean one):

| | all 100 | **the 71 attacked** | the 29 backfilled |
|---|---|---|---|
| P+M | 82% / 0.729 | **87% / 0.767** | 69% / 0.648 |
| P | 66% / 0.569 | **63% / 0.516** | — |
| C  (ceiling) | 86% / 0.781 | **92% / 0.839** | — |
| M | 85% / 0.731 | **90% / 0.787** | — |

Where the poisoning landed the defense recovers 63% → 87% against a 92% clean ceiling. **It does
not beat memory alone** (87% vs 90%; 82% vs 85% overall) — "merging beats closed-book memory"
remains unproven, and that subset is 58 R / 13 S, a skew that favours both.

### The claim set

The literal first 100 binary claims in dev order. This is **not** 05/'s or 12/'s set. 03/ took
the binary claims among dev ids 0-99 that clean InFact judged *correctly* (53 of them), 05/ added
47 more from id 100 upward with no such filter, and 12/ used a seed-42 50/50 sample. Only this set
has one selection rule and no "clean side got it right" filter baked in — the price being that 29
claims are ineligible for attack (Fact2Fiction only attacks claims the clean checker got right),
hence the backfill above.

## 14_binary100_pr008/ + 15_binary100_pr008_fix2/ — the ablation behind 16/

Same claim set, same answers (15/ and 16/ symlink 14/'s `questions.json` and `answers_*.json`, and
reuse its `verdicts_{C,P,M}` unchanged — those arms read no merged record and are unaffected).
Only the merge and judge prompts differ:

| run | `agree` branch | confidence wording | judge extra rules | P+M |
|---|---|---|---|---|
| 14/ | strips attribution | `--conf-rules v1` | `--judge-rules v1` | 67.0% / 0.527 |
| 15/ | **keeps it** | `--conf-rules v1` | `--judge-rules v1` | 66.0% / 0.547 |
| 16/ | **keeps it** | **`v2`** | **`v2`** | **82.0% / 0.729** |

**The whole 16-point gain is the confidence-wording + judge-rule change.** Restoring attribution
on its own moves nothing measurable: 15/'s two judge runs give 66% and 71% against 14/'s 67%, all
inside the judge's own noise. The record got more complete, but the judge went on deciding
conflicts by which side wrote in more detail, so nothing downstream changed. See the comment
blocks above `CONF_RULES_V1` and `JUDGE_EXTRA_RULES_V1` in `exp06_prompts.py` for the measured
defects each version fixes.

**Judge stability is itself a result.** Arm P+M re-run on a byte-identical record flipped **11 of
71** verdicts under 15/ and **1 of 71** under 16/. Giving the judge an actual tiebreaker did not
just raise the score, it stopped the coin-flipping. Corollary: every single-run arm number in this
repo carries roughly ±7pp of judge noise — 14/'s P+M = 67% could have been anywhere in 60-75%.
Two runs per arm is the honest protocol; it is deliberately *not* the default, and is worth doing
only after a configuration's first pass is known to work.

**Known caveat, present in every run including the baselines.** InFact's record format prints a
`Source URL:` line, and Fact2Fiction suffixes planted URLs with `/created` — so the attack's own
marker is visible to every poisoned-arm judge. It is identical across 14/15/16 so the ablation is
unaffected, and no judge rationale was found using it (the 43-44 hits in arms P/PM are the judge
copying URLs into markdown links). Any future claim that the defense *detects* poisoning must
close this first.

## 12_final_100claim/ — superseded by 16/

100 AVeriTeC dev claims, seed 42, 50 gold-Supported / 50 gold-Refuted. Four arms scored on one
claim set: `C` clean retrieval, `P` poisoned retrieval, `P+M` poisoned merged with model-only
memory, `M` memory alone.

Pooled and scored from 10/ and 11/ by `exp08_final_report.py` (analysis only, no LLM calls). See
that directory's README for why the claim set is split in two and why the poisoned arms are
backfilled rather than reported at n=84.

## 10_verdict_84claim/ + 11_cm_only_16claim/ — raw pipeline output for 12/

The two halves of 12/'s claim set: the 84 claims Fact2Fiction attacked (all four arms) and the 16
it skipped (arms C, M, CM only — no poisoned corpus exists for them). Read 12/ instead unless you
need per-question records.

Pipeline for both (`experiments/exp06_*.py`, `--run-dir` selects the directory):

```
exp06_pose_questions.py   → questions.json          (stages 1&2, once; shared by all arms)
exp06_answer_infact.py    → answers_{clean,poisoned}.json   (stages 3&4, one question at a time)
exp06_answer_model_only.py→ answers_model_only.json (closed-book answer + Self-Probing confidence)
exp06_adjudicate.py       → results_*_vs_mo.json, merged_records_*   (agree/conflict + merge)
exp06_judge.py            → verdicts_<arm>_dropempty.json  (stages 5&6 on a record we assemble)
exp08_final_report.py     → <run-dir>/final/{report.md,metrics.csv,verdicts_pooled.json}
```

`exp09_build_claimset.py` assembles a new run dir from existing ones by claim id (14/ reused 74 of
its 100 claims that way); `--sides clean,poisoned` on `exp06_adjudicate.py` builds each side over
its own claim set, so the clean table keeps all 100 claims even when only 71 were attacked.

`13_pr001_84claim/` and `14_gap26/` are scratch: the poison-rate-0.01 pipeline (attack artifacts
only so far) and the 26-claim gap run that `exp09_build_claimset.py` merged into 14/.

## 06_symmetric_conflict/ · 07_verdict_40claim/ · 08_verdict_59claim/ — earlier claim sets

Same pipeline, earlier and smaller claim sets (10, 40, 59 claims), pooled by `exp06_pool.py`.
Superseded by 16/ as the headline number, but they hold results it does not: the merge
development history, the judge-instability measurement (arms re-run twice), and the exp07 debate
arms (`debate_*.json` in 07/) whose negative result is written up in commit `a7f40ae`.

`06_symmetric_conflict_confv1/` is the pre-Self-Probing confidence design, kept for comparison.
`06_smoke/` is a one-claim smoke test. `09_supported6/` is a dead end — see its `DEAD_END.md`.

## 05_mimo_100claim_fusion/ — superseded by 12/

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
