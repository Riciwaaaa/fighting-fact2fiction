# Internal knowledge under changing retrieval reliability

Status: complete development study. The policy and both rate extensions were recorded before their
new counter-evidence reports were collected, but the method was designed and refined on previously
opened development claims. It is not independent confirmation.

## The story in plain words

The result supports the proposed two-regime story, with two qualifications.

1. The defense does not know the nominal poisoning rate at inference time. It observes how often
   one model's answerable, retrieval-free majority conflicts with that model's RAG verdict over a
   batch or time window, and compares this rate with the same model's clean behavior.
2. Under severe corruption, the best fallback is not unconditional model-only. Use the internal
   majority whenever the three sealed calls give a binary answer, but retain RAG as a last resort
   when internal memory is unanswerable. This answerability fallback can recover facts absent from
   model memory without allowing RAG to overturn an answerable internal judgment.

Thus the method has two scales:

- **Claim scale:** three sealed same-model answers establish an internal anchor. When retrieval
  behavior looks normal, a second retrieval view may overturn the anchor only if it independently
  corroborates exactly one endpoint.
- **Environment scale:** the batch-wide rate of RAG/internal conflicts determines how demanding
  that corroboration must be. Mild deviation requires direct, unopposed evidence. Extreme
  deviation disables retrieval-based overrides and uses the memory-first answerability fallback.

This is not a free-form arbiter and it does not locate poisoned passages. LLM calls extract the
semantic signals; a typed policy enforces what those signals are allowed to do.

## Inference-time policy

For each victim model, first estimate its clean reference from claims that do not require gold or
Fact2Fiction eligibility filtering. A claim contributes one observation only if the three
retrieval-free calls have a binary majority. The observation is whether the RAG verdict disagrees
with that majority.

For an inference window, compute the posterior-predictive probability of seeing at least the
observed number of disagreements under the model's clean reference. The implementation uses a
Beta-binomial model with a Jeffreys `Beta(0.5, 0.5)` prior and requires at least 40 answerable
claims. Neither nominal rate, attacker identity, poison provenance, retrieved poison exposure, nor
gold is available to the policy.

| Clean predictive tail | Interpretation | Allowed decision |
|---|---|---|
| `> 0.01` | RAG behavior resembles clean | Answerability fallback plus loose directional corroboration from the leave-original-out view |
| `(0.0001, 0.01]` | RAG behavior is suspicious | Only unopposed direct corroboration may override the fallback |
| `<= 0.0001` | RAG behavior is severely abnormal | No retrieval-based override; use binary internal majority, else RAG |

The cutoffs were frozen before collecting the 0.75%/1% reports, and the unchanged policy plus its
4%/8% evaluation scope was recorded before collecting the high-rate reports. These are clean
predictive budgets, not hidden mappings from nominal poisoning rate.

## Full development curve

Every attacked column uses the identical 227 victim/claim pairs that pass Fact2Fiction's
victim-specific clean-correct filter. Clean uses all 300 model/claim pairs. `Always blend` is the
previous leave-original-out method at every rate. `Memory-first` uses a binary internal majority
and otherwise RAG. The proposed column conditions its evidence standard on observed disagreement.

| Condition | Rows | RAG | Model-only | Memory-first | Always blend | Proposed |
|---|---:|---:|---:|---:|---:|---:|
| Clean | 300 | 227 | 207 | 237 | 244 | **244** |
| 0.1% | 227 | 182 | 175 | 200 | 208 | **208** |
| 0.25% | 227 | 177 | 175 | 200 | 210 | **210** |
| 0.5% | 227 | 151 | 175 | 195 | 202 | **202** |
| 0.75% | 227 | 132 | 175 | 195 | 197 | **197** |
| 1% | 227 | 113 | 175 | **192** | **192** | 191 |
| 4% | 227 | 70 | 175 | **183** | 156 | 179 |
| 8% | 227 | 51 | 175 | **182** | 127 | **182** |

The policy beats both raw endpoints at every reported attacked rate when pooled across models. It
does not uniformly beat the best ablation: it is one case below both memory-first and always-blend
at 1%, and four cases below memory-first at 4%. At 4%, the loss comes entirely from Llama remaining
in the warning tier, where four strict counter-evidence overrides are wrong. This is a useful
boundary, not a result to hide.

The severe-rate ablation is decisive about safety. At 4%, conditioning prevents 23 errors relative
to always blending and introduces none (paired exact `p=2.38e-7`). At 8%, it prevents 55 and
introduces none (`p=5.55e-17`). At 8%, it also improves on unconditional model-only by seven cases
and loses none (`p=0.0156`), because the internally unanswerable cases can still fall back to RAG.

## Same model in all roles

The high-rate experiment uses the same model for the original RAG endpoint, the three internal
calls, and the independent evidence report.

| Model | Rate | Observed mode | RAG | Model-only | Memory-first | Always blend | Proposed |
|---|---|---|---:|---:|---:|---:|---:|
| GLM 5.2 | 4% | severe | 21 | 70 | 70 | 60 | **70** |
| GLM 5.2 | 8% | severe | 11 | 70 | 70 | 46 | **70** |
| Llama 3.1 70B | 4% | suspicious | 36 | 47 | **55** | 51 | 51 |
| Llama 3.1 70B | 8% | severe | 32 | 47 | **54** | 47 | **54** |
| Qwen 3.5 35B-A3B | 4% | severe | 13 | 58 | 58 | 45 | **58** |
| Qwen 3.5 35B-A3B | 8% | severe | 8 | 58 | 58 | 34 | **58** |

At 8%, the defense is strictly above both raw endpoints for Llama and ties model-only for GLM and
Qwen. The pooled win over model-only comes from Llama's selective abstention. At 4%, Llama shows
that a three-tier boundary cannot perfectly map every continuous degradation pattern.

## Why observed behavior is better than nominal rate

The most informative transfer diagnostic comes from the disjoint but previously opened 1% crossed
attacker-victim matrix. The detector receives neither the rate nor attacker identity. It raises no
alarm on any of the three clean victim windows and alarms on six of nine attacked windows:

- all three GLM-generated attack environments alarm;
- all three Qwen-generated attack environments alarm;
- none of the three Llama-generated attack environments alarm.

This matches realized difficulty. On the common 61 claims, Llama-generated attacks leave RAG at
47--54 correct across victims, whereas GLM-generated attacks leave only 22--28 correct and
Qwen-generated attacks leave 27--42. A hard rule saying “1% means model-only” would discard useful
RAG behavior in the weak-attacker cells. The clean-calibrated conflict rate instead responds to
what the victim actually experiences.

This transfer test is frozen relative to the environment detector but not an untouched test: its
claims and endpoint labels had been opened by earlier research cycles. It supports mechanism
plausibility, not a confirmatory performance claim.

## Collection and audit

The 0.75%/1% extension contains 232 disagreement rows and 128 unique model/claim plans. Its source
evidence run references 360 unique cached calls and 1,033,187 tokens; its counter-evidence run
references 232 calls and 1,257,056 tokens. Both audits pass with zero failure.

The 4%/8% extension contains 308 disagreement rows and 166 unique model/claim plans. Its source
evidence run references 474 unique cached calls and 1,201,540 tokens; its counter-evidence run
references 308 calls and 1,218,997 tokens. Both audits pass with zero failure. Across both rate
extensions, the accepted records reference 1,374 unique calls and 4,710,780 tokens. This is cache
accounting, not a price estimate, and some reusable plan calls were already cached.

The second retrieval is not clean. It excludes all original document IDs and exact texts but does
not inspect poison provenance. At 4%, 835/2,485 retrieved counter-view documents are poisoned and
127/145 disagreement rows see at least one. At 8%, the corresponding values are 2,375/3,644 and
161/163. Always blending collapses precisely because repeated retrieval is also compromised; the
environment policy protects the internal anchor in this case.

## What the experiment establishes

The defensible workshop-level insight is:

> Internal knowledge has two roles under retrieval poisoning: it supplies a claim-level fallback
> when retrieval and memory conflict, and its clean-calibrated disagreement with RAG measures when
> the retrieval environment has become too unreliable to overturn that fallback. Independent
> retrieval helps in the mild regime but must lose authority as disagreement becomes abnormal.

This is more informative than “use model-only at high poisoning rates” because the method does not
observe a rate and because attack generators at the same rate have very different realized
effects. It is also more robust than always applying the successful low-rate blend.

The current result does **not** establish:

- independent generalization after the policy was selected;
- per-claim poison detection or exact localization of malicious evidence;
- immediate protection of the first claims in a stream;
- robustness to sparse attacks that stay within the clean disagreement budget;
- robustness to an adaptive attacker that targets internal misconceptions or poisons multiple
  independent retrieval views;
- a strict win over model-only for every model/rate cell;
- superiority of a free-form LLM arbiter. Cached free-form controllers were consistently weaker
  than the typed evidence policy.

## Recommended next experiment

Freeze the complete policy now and evaluate it once on genuinely fresh claims. Use model-specific
clean reference windows and hide nominal rate/attacker metadata from inference. The minimum useful
matrix is clean plus 0.1%, 0.5%, 1%, 4%, and 8% for all three victims; include at least one fixed
strong attacker and one weaker attacker at the same nominal rate. Report both batch-end performance
and an online curve after 10, 20, 40, and all answerable observations, because detection delay is a
real deployment cost.

Required baselines are poisoned RAG, unconditional model-only, memory-first answerability,
always-loose corroboration, always-strict corroboration, and an oracle choosing the better raw
endpoint. A small adaptive attack should (a) target stable internal errors and (b) duplicate its
story into documents likely to survive leave-original-out retrieval. The primary claim should pass
only if the frozen method exceeds both raw endpoints in aggregate while preserving clean utility;
every per-model/rate cell must still be reported.

## Reproduction artifacts

- Base protocol and refinements:
  `configs/environment_drift_gate_v1.json`,
  `configs/environment_drift_gate_v1_amendment_1.json`, and
  `configs/environment_drift_gate_v1_amendment_2.json`
- Complete frozen candidate: `configs/environment_conditioned_candidate_v1.json`
- Detector and policy: `src/parametric_rag_defense/environment_drift.py`
- Collection wrappers: `scripts/run_evidence_signal_rate_extension.py` and
  `scripts/run_evidence_signal_high_rate_extension.py`
- Evaluation: `scripts/evaluate_environment_drift_gate.py` and
  `scripts/evaluate_tiered_environment_policy.py`
- Detection/cross-claim diagnostic: `artifacts/evaluation/environment_drift_gate_v1.json`
- Complete curve: `artifacts/evaluation/tiered_environment_policy_high_rate_v1.json`
- Source/counter runs:
  `artifacts/runs/{evidence_signal,counter_retrieval}/*rate075_1pct_v1/` and
  `artifacts/runs/{evidence_signal,counter_retrieval}/*rate4_8pct_v1/`
