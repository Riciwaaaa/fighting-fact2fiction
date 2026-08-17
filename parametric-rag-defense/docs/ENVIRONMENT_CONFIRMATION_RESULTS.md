# Fresh confirmation results: internal knowledge as a RAG safety anchor

## Bottom line

The frozen method passed its predeclared fresh-confirmation gate. On 1,260 attacked same-model
rows, it reaches **80.48%**, compared with **48.97%** for poisoned RAG and **73.02%** for the
three-call closed-book majority. Its paired advantage is 31.51 percentage points over RAG and
7.46 points over closed book. On 300 clean rows it scores **83.67%**, compared with **84.00%** for
clean RAG.

The prespecified attacker-transfer secondary is also positive. Across 414 rows at 1% poisoning,
with GLM- and Llama-generated poison crossed with all three victims, the frozen method reaches
**83.09%**, versus **58.94%** for RAG and **76.33%** for closed book. The attacker identity is used
only to define reporting cells and never enters the defense.

These results support a workshop-level claim:

> An LLM's internal answer is useful both as a fallback and as a corpus-level warning signal.
> When retrieval and internal answers disagree unusually often, the system should stop allowing
> retrieval to overrule the internal anchor. When the environment looks normal, an independent
> view from the same corpus can recover useful RAG information.

The method does **not** identify poisoned passages, does not dominate every cell, and is not a
single-query detector. It is a policy for repeated queries in a shared retrieval environment.

## What the method does, in plain words

For each claim, the same model is called three times without retrieval. Their deterministic
majority is the internal-memory answer. The ordinary RAG workflow independently returns its
verdict.

1. If internal memory is not binary-answerable, fall back to RAG. Otherwise, internal memory is
   the default.
2. Across a batch of claims in one shared retrieval environment, count how often answerable
   internal memory disagrees with RAG. Compare that count with a model-specific clean reference
   frozen on the earlier development data.
3. If disagreement is at its normal clean-like level, a RAG/internal disagreement may be resolved
   using a second view: reuse the RAG-generated questions, exclude every document and exact text
   used by the first RAG answer, retrieve again from the **same possibly poisoned corpus**, and ask
   the same model for an endpoint-hidden evidence map.
4. If disagreement is moderately abnormal, require stricter, direct, unopposed corroboration. If
   it is severely abnormal, disable retrieval overrides and retain the answerability fallback.

The defense never receives the nominal attack rate, attacker name, poison labels, retrieved-poison
count, gold label, or endpoint correctness. The second retrieval is not clean: at nominal rates
0.1%, 0.5%, 1%, 4%, and 8%, its private poison-document fractions are respectively 0.16%, 0.40%,
1.70%, 27.87%, and 62.64% on disagreement rows.

## Confirmation protocol

- Data: 100 AVeriTeC train claims not previously used in this project, with 50 Supported and 50
  Refuted labels and zero exact claim/date overlap with the prior development set.
- Fact2Fiction convention: only binary labels; for attacked evaluation, each victim uses only
  claims its clean RAG endpoint answered correctly.
- Clean rows: 100 per model, or 300 total.
- Attacked eligibility: GLM 89 claims, Llama 86, Qwen 77.
- Conditions: clean plus nominal Fact2Fiction rates 0.1%, 0.5%, 1%, 4%, and 8%.
- Primary roles: the same model is poison generator, RAG victim, three-call closed-book endpoint,
  and evidence reporter.
- Models: GLM 5.2, Llama 3.1 70B Instruct, and Qwen 3.5 35B A3B through NVIDIA endpoints.
- Freeze: protocol commit `ccd69bb`; the method, thresholds, baselines, and success gate were
  fixed before fresh model inference.

The fresh split is a research-process holdout, not proof that public hosted base models never saw
AVeriTeC during pretraining.

## Primary result

### Predeclared gate

All three conditions pass:

- attacked pooled proposed accuracy is strictly above both raw endpoints;
- at least one victim has a pooled attacked win over both raw endpoints—in fact, all three do;
- clean pooled proposed accuracy is within two points of the stronger clean raw endpoint.

### Pooled results

| Scope | Rows | RAG | Closed book | Answerability fallback | Proposed |
|---|---:|---:|---:|---:|---:|
| Clean | 300 | **84.00** | 68.67 | 82.00 | 83.67 |
| All attacked rates | 1,260 | 48.97 | 73.02 | 80.16 | **80.48** |

On attacked rows, proposed versus RAG has 435 proposed-only correct cases and 38 RAG-only correct
cases (net +397, exact paired p = 1.65e-86; claim-cluster bootstrap 95% accuracy-difference
interval +25.90 to +36.96 points). Proposed versus closed book is 97 to 3 (net +94, p =
2.63e-25; interval +4.94 to +10.31 points).

On clean rows, proposed versus RAG is 20 to 21 (net -1, p = 1.0; interval -5.00 to +4.33
points). There is no evidence of a pooled clean-accuracy difference.

### Results by nominal rate

| Rate | Rows | Selected environment states | RAG | Closed book | Fallback | Proposed |
|---|---:|---|---:|---:|---:|---:|
| 0.1% | 252 | all normal | 80.16 | 73.02 | 86.90 | **88.10** |
| 0.5% | 252 | all normal | 71.43 | 73.02 | 83.73 | **84.52** |
| 1% | 252 | GLM critical; Llama normal; Qwen warning | 50.00 | 73.02 | **80.56** | 80.16 |
| 4% | 252 | all critical | 25.00 | 73.02 | **75.00** | **75.00** |
| 8% | 252 | all critical | 18.25 | 73.02 | **74.60** | **74.60** |

This is the central empirical pattern. At low rates, the independent same-corpus view adds useful
information beyond both RAG and closed book. At severe rates, that view is heavily poisoned and
the environment warning correctly turns it off. At 1%, the method remains above both raw
endpoints but is one case below the simpler answerability fallback; the paper should report this
instead of claiming universal benefit from counter retrieval.

### Results by victim, pooled across all five attacked rates

| Victim | Rows | RAG | Closed book | Fallback | Proposed | Proposed–memory 95% CI |
|---|---:|---:|---:|---:|---:|---|
| GLM | 445 | 39.78 | 77.53 | 80.90 | **81.12** | +1.35 to +6.29 |
| Llama | 430 | 67.67 | 63.95 | **81.16** | 80.93 | +11.16 to +23.26 |
| Qwen | 385 | 38.70 | 77.92 | 78.18 | **79.22** | -0.52 to +3.12 |

All three point estimates exceed both raw endpoints. Qwen's +1.30-point gain over closed book is
not statistically resolved, and Llama's answerability fallback is one case better than proposed.
These distinctions matter: the broad aggregate claim is well supported, but per-model superiority
over every simpler policy is not.

### Complete victim-by-condition table

| Victim | Condition | State | RAG | Closed book | Fallback | Proposed |
|---|---|---|---:|---:|---:|---:|
| GLM | clean | normal | 89.00 | 72.00 | 83.00 | 85.00 |
| GLM | 0.1% | normal | 71.91 | 77.53 | 85.39 | 85.39 |
| GLM | 0.5% | normal | 66.29 | 77.53 | 83.15 | **84.27** |
| GLM | 1% | critical | 39.33 | 77.53 | **80.90** | **80.90** |
| GLM | 4% | critical | 13.48 | 77.53 | **77.53** | **77.53** |
| GLM | 8% | critical | 7.87 | 77.53 | **77.53** | **77.53** |
| Llama | clean | normal | 86.00 | 60.00 | 87.00 | **88.00** |
| Llama | 0.1% | normal | **95.35** | 63.95 | **95.35** | **95.35** |
| Llama | 0.5% | normal | 87.21 | 63.95 | **89.53** | **89.53** |
| Llama | 1% | normal | 70.93 | 63.95 | **82.56** | 81.40 |
| Llama | 4% | critical | 46.51 | 63.95 | **69.77** | **69.77** |
| Llama | 8% | critical | 38.37 | 63.95 | **68.60** | **68.60** |
| Qwen | clean | normal | 77.00 | 74.00 | 76.00 | **78.00** |
| Qwen | 0.1% | normal | 72.73 | 77.92 | 79.22 | **83.12** |
| Qwen | 0.5% | normal | 59.74 | 77.92 | 77.92 | **79.22** |
| Qwen | 1% | warning | 38.96 | **77.92** | **77.92** | **77.92** |
| Qwen | 4% | critical | 14.29 | **77.92** | **77.92** | **77.92** |
| Qwen | 8% | critical | 7.79 | **77.92** | **77.92** | **77.92** |

The clean trade-off is not uniform: proposed is four points below clean RAG for GLM, two points
above it for Llama, and one point above it for Qwen. The predeclared clean gate was pooled.

### Online versus batch-end detection

The headline policy assigns a state after seeing the complete victim-condition cell. The frozen
online simulation orders claims deterministically, uses only prior rows, and stays in normal mode
until 40 answerable observations. It scores 965/1,260 = **76.59%** over attacked rows, still above
closed book at 73.02% and RAG at 48.97%, but below the 80.48% batch-end result. The loss is
concentrated at 4% and 8% while the detector accumulates enough evidence.

This should be framed honestly: the method is immediately suitable for periodic monitoring of a
shared knowledge base, while abrupt online poisoning needs a faster sequential detector or a safe
initialization policy.

## Attacker-transfer secondary

The secondary uses the 69 claims on which all three victims' clean RAG verdicts are correct. GLM
and Llama provide fixed 1% poison prefixes, and each attacks all three victims. The complete matrix
has 414 rows. Diagonal rows reuse the primary artifacts; off-diagonal rows run the unchanged victim
pipeline.

### Pooled transfer result

| Rows | RAG | Closed book | Fallback | Loose | Strict | Proposed |
|---:|---:|---:|---:|---:|---:|---:|
| 414 | 58.94 | 76.33 | 82.61 | 82.85 | **83.33** | 83.09 |

Proposed versus RAG is 112 to 12 paired exclusive wins (net +100, p = 1.67e-21; clustered 95%
interval +17.39 to +31.16 points). Proposed versus closed book is 31 to 3 (net +28, p = 7.66e-7;
interval +3.14 to +10.87 points). The strict fixed ablation is one case above proposed, so the
environment gate is not the best secondary policy on this single 1% scope; its value is across the
full rate curve.

### All six attacker-victim cells

| Attacker | Victim | State | RAG | Closed book | Fallback | Proposed |
|---|---|---|---:|---:|---:|---:|
| GLM | GLM | critical | 43.48 | 79.71 | **84.06** | **84.06** |
| GLM | Llama | critical | 43.48 | 69.57 | **76.81** | **76.81** |
| GLM | Qwen | normal | 39.13 | **79.71** | **79.71** | 78.26 |
| Llama | GLM | normal | 84.06 | 79.71 | 86.96 | **89.86** |
| Llama | Llama | normal | 72.46 | 69.57 | **86.96** | 85.51 |
| Llama | Qwen | normal | 71.01 | 79.71 | 81.16 | **84.06** |

GLM poison causes critical drift for GLM and Llama victims but only normal drift for Qwen under
the fixed Qwen reference. Llama poison produces normal drift in all three cells. This confirms the
earlier observation that nominal rate alone does not define attack severity.

The method is not universally dominant: for GLM→Qwen it is one case below closed book/fallback.
Pooled across the two attackers, however, proposed beats both raw endpoints for each victim:

| Victim | Rows | RAG | Closed book | Proposed |
|---|---:|---:|---:|---:|
| GLM | 138 | 63.77 | 79.71 | **86.96** |
| Llama | 138 | 57.97 | 69.57 | **81.16** |
| Qwen | 138 | 55.07 | 79.71 | **81.16** |

The Qwen advantage over closed book is again small and statistically unresolved; GLM and Llama
show clearer gains.

## Integrity and fairness checks

- Primary original-view evidence audit: 787/787 disagreement rows; 251 reusable neutral plans;
  zero failures or prompt leaks.
- Primary counter-view audit: 787/787 reports; zero exclusion, reconstruction, same-model, cache,
  contract, or prompt-isolation failures.
- Transfer audit: 414/414 endpoints in six balanced cells and 188/188 counter reports; zero
  failures.
- Every counter view excludes all original document IDs and exact-text hashes.
- Every counter view uses the same clean-or-poisoned corpus as its corresponding RAG endpoint.
- The model sees neutral passage aliases, not attacker/victim IDs, condition IDs, raw URLs, or
  clean/poison provenance.
- Gold is joined only by evaluation scripts after output collection and audit.

Three operational amendments are retained rather than hidden:

1. The generic prompt renderer now distinguishes template variables from literal braces inserted
   by retrieved documents.
2. One visual-separator retrieval item containing only underscores is removed from original-view
   packets because it has no factual proposition to assess.
3. The identical no-alphanumeric rule is applied to one counter-view separator. All substantive
   passages remain unchanged.

These amendments are mechanically detectable without labels, correctness, endpoints, model
confidence, attacker identity, rate, or poison provenance. Their exact triggers and hashes are in
the protocol amendment files.

## Calls and retained artifacts

The isolated confirmation cache contains 7,098 unique request entries and 23,147,637 total tokens
(18,539,326 prompt; 4,608,311 completion), including retained format-repair attempts and the
attacker-transfer secondary.

| Request stage | Unique cache entries | Total tokens |
|---|---:|---:|
| Three-call closed book | 901 | 587,567 |
| RAG question planning | 300 | 211,146 |
| Fact2Fiction blueprints | 268 | 468,164 |
| RAG question answering | 1,813 | 10,485,376 |
| RAG final verdict | 1,764 | 2,973,390 |
| Neutral claim plan | 256 | 151,595 |
| Original-view passage map | 825 | 3,384,409 |
| Counter-view passage map | 971 | 4,885,990 |

The count is of content-addressed provider requests, not logical workflow edges: identical cached
requests are executed once, while each retained contract-repair prompt has its own cache entry.

Key artifacts:

- frozen primary protocol: `configs/environment_confirmation_protocol_v1.json`;
- operational amendments: `configs/environment_confirmation_protocol_v1_amendment_{1,2,3}.json`;
- frozen transfer protocol: `configs/environment_attacker_transfer_v1.json`;
- primary endpoint table: `artifacts/evaluation/environment_confirmation_train_v1/endpoint_summary.json`;
- primary full result: `artifacts/evaluation/environment_confirmation_train_v1/environment_conditioned_results.json`;
- primary evidence audit: `artifacts/runs/environment_confirmation_train_v1/evidence_signal/environment_confirmation_evidence_v1/audit.json`;
- primary counter audit: `artifacts/runs/environment_confirmation_train_v1/counter_retrieval/environment_confirmation_counter_v1/audit.json`;
- transfer full result: `artifacts/evaluation/environment_confirmation_train_v1/attacker_transfer_results.json`;
- transfer audit: `artifacts/runs/environment_confirmation_train_v1/attacker_transfer_counter/environment_confirmation_transfer_counter_v1/audit.json`;
- chronological execution notes: `docs/ENVIRONMENT_CONFIRMATION_LOG.md`.

Raw prompts, responses, receipts, neutral plans, source packets, retrieval exclusions, passage maps,
and private poison-exposure diagnostics remain in the Git-ignored artifact tree. Successful calls
do not need to be repeated for later error analysis.

## What is defensible in a paper

The strongest defensible framing is not “the LLM detects poisoned documents.” The evidence mapper
often treats fluent poison as direct evidence, especially at high rates. The defensible insight is
two-scale:

- claim-level internal knowledge supplies an independent answer and an answerability signal;
- environment-level RAG/internal disagreement reveals when retrieval has stopped behaving like a
  clean system;
- same-corpus corroboration is useful only while that environment signal remains normal.

This explains both sides of the curve using one fixed policy: blend at low attack strength and
fall back toward internal knowledge when retrieval drift is severe. The cross-attacker result
shows that this is not merely a same-generator/same-victim artifact.

## Limitations reviewers should see explicitly

- The confirmation set has only 100 claims and comes from a public benchmark. Clustered intervals
  account for repeated rates/attackers but do not create more independent claims.
- Fact2Fiction is non-adaptive. An attacker that targets the internal anchor, the disagreement
  statistic, or counter retrieval is not tested.
- The batch-end result assumes many queries share one retrieval environment. The online simulation
  is weaker during its first 40 answerable observations.
- Clean utility is pooled. GLM loses four clean points even though Llama and Qwen gain.
- Qwen's pooled advantage over closed book is a small, statistically unresolved point estimate in
  both primary and transfer analyses.
- At 1%, the simple answerability fallback is one primary case above proposed; in the transfer
  secondary, always-strict corroboration is one case above proposed.
- The second retrieval increases computation and is not independent of corpus poisoning. Its
  fairness is strong—same corpus, no provenance—but its evidence is unsafe at high rates.
- Thresholds and clean references were selected on prior development data. These confirmation
  claims must not be reused to tune a replacement policy and then presented as independent.

## Recommended workshop paper and next experiments

For the current workshop paper:

1. Lead with the broad conditional question: when can internal knowledge protect RAG?
2. Present the rate curve and state transition as the main result, not a claim of universal
   endpoint arbitration.
3. Use the three raw endpoints/ablations—RAG, closed book, and answerability fallback—plus always
   loose, always strict, proposed, and the two-endpoint oracle.
4. Report the complete model/rate and attacker/victim tables, batch and online results, paired
   tests, clustered intervals, clean trade-offs, and poison exposure.
5. Include representative successes and failures using the retained passage maps; no new model
   calls are needed.

The most valuable additional experiments, in order, are:

1. A second independent dataset or knowledge corpus with the same frozen policy.
2. A faster sequential change detector and safe warm-up policy, evaluated on abrupt attack onset.
3. Adaptive attacks that jointly target internal answers, disagreement monitoring, and counter
   retrieval.
4. One additional victim family and more attacker generators to separate model-specific from
   corpus-specific effects.
5. A reduced-cost variant that calls the counter view only for high-value disagreements while
   retaining the environment gate.

Do not tune on the 100 confirmation claims and report the same table as new validation. They are
now open and should be used only for diagnosis, qualitative analysis, or explicitly labeled
method development.
