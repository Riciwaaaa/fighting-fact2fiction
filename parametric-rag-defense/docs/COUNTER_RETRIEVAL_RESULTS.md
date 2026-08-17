# Leave-original-out corroboration: development results

Status: complete post-label method-development result. This is the strongest current candidate,
but it has not been evaluated on fresh claims after method selection.

## Result in one sentence

The useful signal is not whether the original retrieved text sounds correct. It is whether the
claim receives direct support or refutation from a second retrieval view after every document and
exact passage in the original top-k has been excluded.

On the current development claims, a same-model workflow using that signal beats both model-only
and poisoned RAG for all three victim models at 0.1%, 0.25%, and 0.5% poisoning.

## Primary same-model method

The candidate acts only when a model's RAG verdict and its three-sample closed-book majority
disagree.

1. Run the same model's RAG endpoint and three cached closed-book assessments.
2. Use the RAG run's ten claim-generated search questions, but retrieve again after excluding all
   original document identities and all exact duplicate texts. Select up to five nearest eligible
   documents per query and remove repeats across queries without backfilling.
3. Ask the same model for a structured, endpoint-hidden report of what this independent passage
   set supports or refutes. The reporter sees no endpoint label, model identity, condition, rate,
   origin, URL, poison count, or gold.
4. Start from an answerability fallback: use the closed-book majority when it is `Supported` or
   `Refuted`; otherwise use RAG.
5. If the independent report has a directional label matching exactly one endpoint, copy that
   endpoint. Otherwise retain the answerability fallback.

This final aggregation is deliberately typed rather than free-form. The LLM performs the hard
semantic work—claim decomposition and evidence interpretation—but it cannot ignore its own
corroboration result or introduce a third verdict.

The prototype consumed the earlier original-passage experiment for cached plans, queries, and
scope. A clean implementation of the candidate does not require the original-passage LLM report;
it needs only the original retrieved document identities/text hashes, the second retrieval view,
and its evidence report.

## Audit and independence check

All 363 disagreement cases completed and passed reconstruction and inference-boundary audits.
The first map pass had two network read timeouts; an idempotent retry reused all 361 successful
cache entries and completed the missing two without changing the protocol.

| Condition | Disagreement rows | Mean second-view documents | Poison documents | Poison fraction | Rows exposed |
|---|---:|---:|---:|---:|---:|
| Clean | 100 | 22.28 | 0 | 0.000% | 0/100 |
| 0.1% | 82 | 21.44 | 2 | 0.114% | 2/82 |
| 0.25% | 83 | 21.48 | 2 | 0.112% | 2/83 |
| 0.5% | 98 | 20.78 | 12 | 0.589% | 10/98 |

These private counts were used only after prompts were constructed. The method excludes source
identity and exact text without consulting poison provenance.

The 363 same-model evidence reports reference 2,076,680 tokens: 1,270,222 prompt and 806,458
completion tokens. This is accepted-record accounting, not a provider-price estimate.

## Full-system development accuracy

Endpoint agreements pass through unchanged. The defended count includes the fixed rule only on
endpoint disagreements.

| Condition | Rows | Poisoned RAG | Same-model closed book | Answerability fallback | Corroboration method |
|---|---:|---:|---:|---:|---:|
| Clean | 300 | 227 (75.7%) | 207 (69.0%) | 237 (79.0%) | **244 (81.3%)** |
| 0.1% | 227 | 182 (80.2%) | 175 (77.1%) | 200 (88.1%) | **208 (91.6%)** |
| 0.25% | 227 | 177 (78.0%) | 175 (77.1%) | 200 (88.1%) | **210 (92.5%)** |
| 0.5% | 227 | 151 (66.5%) | 175 (77.1%) | 195 (85.9%) | **202 (89.0%)** |

On the 363 mapped disagreements, the method corrects 34 answerability errors and introduces two
regressions, for a net gain of 32. Only 14 distinct claims are switched, so row-wise significance
would exaggerate the evidence. A claim-clustered bootstrap gives a 95% interval of
`[+3.8, +14.1]` accuracy points for the disagreement-level gain. The per-rate intervals are also
above zero: `[+3.4, +17.2]` at 0.1%, `[+5.8, +19.0]` at 0.25%, and `[+0.9, +13.9]` at 0.5%.

## Same model in every primary role

Each row below uses one model for RAG, closed book, and the second-view evidence report.

| Victim | Condition | Rows | RAG | Closed book | Answerability | Corroboration |
|---|---|---:|---:|---:|---:|---:|
| GLM 5.2 | Clean | 100 | 82 | 80 | 85 | **85** |
| GLM 5.2 | 0.1% | 82 | 60 | 70 | 73 | **75** |
| GLM 5.2 | 0.25% | 82 | 58 | 70 | 73 | **75** |
| GLM 5.2 | 0.5% | 82 | 49 | 70 | 73 | **75** |
| Llama 3.1 70B | Clean | 100 | 72 | 54 | **79** | **79** |
| Llama 3.1 70B | 0.1% | 72 | 63 | 47 | **69** | **69** |
| Llama 3.1 70B | 0.25% | 72 | 64 | 47 | **69** | **69** |
| Llama 3.1 70B | 0.5% | 72 | 55 | 47 | **64** | **64** |
| Qwen 3.5 35B-A3B | Clean | 100 | 73 | 73 | 73 | **80** |
| Qwen 3.5 35B-A3B | 0.1% | 73 | 59 | 58 | 58 | **64** |
| Qwen 3.5 35B-A3B | 0.25% | 73 | 55 | 58 | 58 | **66** |
| Qwen 3.5 35B-A3B | 0.5% | 73 | 47 | 58 | 58 | **63** |

Llama's answerability fallback already equals the two-endpoint oracle on these cells, so the new
signal appropriately makes no change. GLM gains two cases per attacked rate. Qwen gains seven
clean cases and five to eight attacked cases, directly addressing its tendency to give confident
but wrong closed-book answers.

## Why the earlier design failed and this one works

The original evidence mapper was asked to interpret the same top-k that produced RAG. Under
poisoning, a fluent fabricated passage is semantically direct, internally consistent, and often
repeated. The mapper therefore reinforced the poison: its attacked strict direction aligned with
RAG 48 times and was wrong in 41.

After original-document exclusion, the second-view directional signal is sparse but precise. It
overrides the answerability fallback only 36 times: 34 gains and two losses. Most reports remain
`insufficient` or `mixed`; that abstention is useful because absence of an alternative passage is
not treated as proof that the claim is false.

The remaining selectable errors are also structured. Whenever the method chooses the wrong
endpoint but the other endpoint is correct, it has retained a confident wrong memory answer because
the second view was inconclusive. The residual oracle gaps are 9, 5, and 5 cases at the three
attack rates. This suggests that any Stage 4 should gather another independent observation, not
ask the same model to deliberate again over the same summaries.

## LLM controller ablation

A same-model three-action controller was frozen before its calls. It saw endpoint labels, repeated
closed-book reliability fields, original and second-view evidence summaries, and limited RAG
process statistics. It could trust RAG, trust memory, or escalate. All 363 outputs passed audit;
the run used 1,244,542 referenced tokens.

| Condition | Typed corroboration | Raw LLM controller | Guarded LLM controller |
|---|---:|---:|---:|
| Clean | **244** | 241 | 238 |
| 0.1% | **208** | 201 | 203 |
| 0.25% | **210** | 198 | 203 |
| 0.5% | **202** | 189 | 199 |

The controller selected `escalate` 165 times, memory 136 times, and RAG 62 times. Its principal
failure is not missing information: Qwen often continues to trust its stable wrong memory answer
even when the independent report supports RAG, while GLM sometimes trusts uncorroborated original
evidence under attack. A guarded version improves over answerability but rejects 23 correct
counter-rule decisions. This supports a general method insight: use LLMs to extract typed semantic
signals, then enforce the meaning of those signals in the controller boundary.

A claim-grouped endpoint-calibration fusion was also tested without new calls. It ties the typed
method at 0.1% and 0.5%, loses two cases at 0.25%, and loses one clean case. It is retained as a
negative complexity ablation.

## Secondary multi-model plus variant

When same-model counter evidence is inconclusive, a costlier plus variant consults the cached
three-family closed-book majority. Direct same-model corroboration always takes precedence. The
panel changes only 11 rows, all correctly on this development set, representing five distinct
claims.

| Condition | Same-model method | Three-family plus |
|---|---:|---:|
| Clean | 244/300 (81.3%) | **248/300 (82.7%)** |
| 0.1% | 208/227 (91.6%) | **212/227 (93.4%)** |
| 0.25% | 210/227 (92.5%) | **211/227 (93.0%)** |
| 0.5% | 202/227 (89.0%) | **204/227 (89.9%)** |

This is an explicitly secondary accuracy/cost result. It requires closed-book assessments from
all three families at deployment, and its apparent perfect override precision is based on only five
unique claims. It must not replace the same-model result in the primary table.

## What can and cannot be claimed

Supported development claim:

> In a non-adaptive low-rate Fact2Fiction setting, parametric knowledge is useful as a selective
> fallback, while leave-original-out retrieval supplies a high-precision signal for overriding
> confident internal errors. On this development set, their typed combination outperforms both
> endpoints for three same-model victim pipelines.

Not yet supported:

- independent generalization to unseen claims;
- robustness to an attacker aware of document exclusion or the corroboration rule;
- calibrated gains at 1% or stronger poisoning;
- statistical model-general conclusions from three endpoints;
- a claim that free-form LLM arbitration is superior to a typed workflow;
- cost effectiveness without reporting the additional retrieval and mapping tokens.

## Required next experiment

1. Freeze this exact primary rule, retrieval exclusion semantics, prompts, models, rates, decoding,
   and evaluation code as a candidate selected on development data.
2. Select genuinely fresh binary claims that have not been used for method choice. Re-run clean RAG
   and the three low attack rates, then apply Fact2Fiction's victim-specific clean-correct filter.
3. Run the primary same-model method once. Report every victim/rate cell, clean utility, paired
   tests, claim-clustered intervals, switch precision/recall, and total calls/tokens.
4. Retain poisoned RAG, same-model closed book, answerability fallback, original-passage mapping,
   no-exclusion retrieval, the frozen free-form controller, and a shuffled-counter-report control.
5. Run the three-family plus only as a secondary costed variant. Add a small defense-aware attack
   that produces multiple corroborating poison documents if budget permits.

No third retrieval pass is justified before this confirmation. The present method already meets
the practical development goal, and another adaptive query stage would add cost and attack surface
before generalization is established.

## Reproduction artifacts

- Counter-retrieval freeze: `configs/counter_retrieval_signal_v2_freeze.json`
- Counter-retrieval code: `src/parametric_rag_defense/counter_retrieval.py`
- Collection and audit: `scripts/run_counter_retrieval_signal.py` and
  `scripts/check_counter_retrieval_signal.py`
- Primary evaluation: `scripts/summarize_counter_retrieval_signal.py`
- Primary JSON: `artifacts/evaluation/counter_retrieval_signal_v2.json`
- Controller freeze: `configs/corroboration_arbiter_v1_freeze.json`
- Controller run/audit: `artifacts/runs/corroboration_arbiter/corroboration_arbiter_v1/`
- Controller evaluation: `artifacts/evaluation/corroboration_arbiter_v1.json`
- Endpoint-fusion control: `artifacts/evaluation/counter_endpoint_fusion_oof_v1.json`
- Multi-model plus: `artifacts/evaluation/multimodel_corroboration_plus_v1.json`
