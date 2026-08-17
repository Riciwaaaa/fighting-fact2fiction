# Intermediate poisoning-rate scan results

Status: complete development analysis. The protocol was frozen before the new endpoint outputs.

## Bottom line

Lower poisoning rates do create a more meaningful blending problem, but they should be presented as
different operating regimes rather than as a replacement for the 1% result.

- At 0.1%, pooled diagonal RAG is slightly better than same-model closed-book (182/227 versus
  175/227).
- At 0.25%, the two pooled endpoints are nearly tied (177/227 versus 175/227). This is the clearest
  crossover condition for studying whether an evidence-aware workflow can select the right one.
- At 0.5%, RAG falls to 151/227 while same-model closed-book remains 175/227. At 0.75% and 1%, the
  problem is increasingly asymmetric and an internal-knowledge default is more sensible.
- The three-model closed-book majority is a stronger baseline at 192/227 on this selected subset.
  A multi-model hybrid therefore has to beat 192, not merely 177 and 175. At 0.25%, its oracle with
  RAG is 218/227, leaving 26 possible RAG rescues but also 41 opportunities for a bad switch.

This scan supports a paper organized around a rate-dependent robustness/utility tradeoff: blend at
low exposure, become conservative as poisoning rises, and report when model-only is the correct
answer. A deployable workflow must infer risk from observable evidence; it cannot receive the
hidden poisoning rate.

## Scope and integrity

- Dataset: the existing 100-claim balanced binary development set.
- Fact2Fiction eligibility: only victim/claim pairs on which clean RAG was correct.
- Eligible pairs: GLM 82, Llama 72, Qwen 73; 227 total at every attacked rate.
- New rates: 0.25%, 0.5%, and 0.75%; attack seed 101.
- New endpoint workload: 681/681 completed with no runtime failure.
- Reused artifacts: all clean RAG outputs, closed-book outputs, poison blueprints, poison documents,
  embeddings, and cached LLM calls that matched exactly.
- Audit: 981/981 scoped endpoints (300 reused clean plus 681 attacked) passed. There were no missing
  tasks, poison-material failures, or victim-prompt failures. The shared namespace also contains
  908 earlier endpoints at other rates; the scoped audit explicitly allows and reports them.

The audit's 8,872,630 referenced-token total covers all cache entries reachable from the scoped
clean and attacked traces, including reused history. It is not the incremental cost of this scan.

## Seven-rate endpoint curve

Every row uses the same 227 eligible victim/claim pairs. “Panel” is the majority of the three
closed-book model verdicts. “Panel+RAG oracle” is analysis-only: it counts a row correct if either
the panel or RAG is correct and therefore measures maximum selection headroom, not a defense.

| Nominal poison | RAG | Same-model closed-book | Three-model panel | Panel+RAG oracle | Mean injected docs | Poison among retrieved passages |
|---:|---:|---:|---:|---:|---:|---:|
| 0.10% | 182/227 (80.2%) | 175/227 (77.1%) | 192/227 (84.6%) | 220/227 (96.9%) | 1.00 | 5.5% |
| 0.25% | 177/227 (78.0%) | 175/227 (77.1%) | 192/227 (84.6%) | 218/227 (96.0%) | 1.51 | 8.5% |
| 0.50% | 151/227 (66.5%) | 175/227 (77.1%) | 192/227 (84.6%) | 214/227 (94.3%) | 3.58 | 20.8% |
| 0.75% | 132/227 (58.1%) | 175/227 (77.1%) | 192/227 (84.6%) | 213/227 (93.8%) | 5.56 | 32.7% |
| 1.00% | 113/227 (49.8%) | 175/227 (77.1%) | 192/227 (84.6%) | 208/227 (91.6%) | 7.68 | 43.0% |
| 4.00% | 70/227 (30.8%) | 175/227 (77.1%) | 192/227 (84.6%) | 199/227 (87.7%) | 33.10 | 83.9% |
| 8.00% | 51/227 (22.5%) | 175/227 (77.1%) | 192/227 (84.6%) | 195/227 (85.9%) | 69.67 | 92.1% |

The attack is nominally defined as a fraction of the full retrieval corpus, but the operational
difficulty is better reflected by poison exposure in the retrieved top-k passages. Exposure rises
from 5.5% at 0.1% nominal poisoning to 43.0% at 1%.

## Per-model results

The pooled 0.25% crossover must not be mistaken for a per-model crossover. Counts below use each
victim's own clean-correct subset. The parenthesized value is the fixed three-model panel result on
that same subset.

| Victim | Eligible | 0.10% RAG / own memory | 0.25% RAG / own memory | 0.50% RAG / own memory | 0.75% RAG / own memory | 1.00% RAG / own memory |
|---|---:|---:|---:|---:|---:|---:|
| GLM | 82 | 60 / 70 (panel 68) | 58 / 70 (68) | 49 / 70 (68) | 42 / 70 (68) | 33 / 70 (68) |
| Llama | 72 | 63 / 47 (panel 61) | 64 / 47 (61) | 55 / 47 (61) | 52 / 47 (61) | 50 / 47 (61) |
| Qwen | 73 | 59 / 58 (panel 63) | 55 / 58 (63) | 47 / 58 (63) | 38 / 58 (63) | 30 / 58 (63) |

Qwen at 0.1% and 0.25% is the cleanest individually symmetric test. Llama is a useful opposing
case because RAG remains better than its own closed-book answer through 1%. GLM is the reverse:
its own closed-book answer is already the stronger endpoint at every attacked rate tested.

These differences are scientifically useful. A credible workflow should adapt to evidence quality
within a model, not implement one global preference that happens to score well after pooling.

## Selection headroom at the key rates

The endpoint outcome tables show both the opportunity and the risk of blending.

| Rate | Both same-model endpoints correct | RAG only | Own memory only | Neither | Same-model oracle |
|---:|---:|---:|---:|---:|---:|
| 0.10% | 140 | 42 | 35 | 10 | 217/227 (95.6%) |
| 0.25% | 137 | 40 | 38 | 12 | 215/227 (94.7%) |
| 0.50% | 119 | 32 | 56 | 20 | 207/227 (91.2%) |
| 0.75% | 104 | 28 | 71 | 24 | 203/227 (89.4%) |
| 1.00% | 89 | 24 | 86 | 28 | 199/227 (87.7%) |

At 0.25%, a perfect same-model selector could gain 38 cases over RAG and 40 over model-only. The
task is balanced enough to be meaningful, but not easy: an incorrect preference can lose almost
as many cases as it gains.

Against the stronger three-model panel at 0.25%, the outcome counts are 151 both correct, 26 RAG
only, 41 panel only, and 9 neither. Thus a panel-assisted workflow has real headroom, but its prior
should favor the panel unless the evidence provides a reliable reason to switch.

## Rate behavior is aggregate, not deterministic

RAG accuracy declines nearly monotonically in aggregate, but individual paths sometimes recover
at a higher rate. Across adjacent rates, correct-to-wrong versus wrong-to-correct transitions are:

| Transition | Correct → wrong | Wrong → correct |
|---|---:|---:|
| 0.10% → 0.25% | 7 | 2 |
| 0.25% → 0.50% | 29 | 3 |
| 0.50% → 0.75% | 25 | 6 |
| 0.75% → 1.00% | 23 | 4 |
| 1.00% → 4.00% | 46 | 3 |
| 4.00% → 8.00% | 22 | 3 |

Twenty-one of 227 victim/claim paths regain a correct RAG verdict at least once as the rate rises.
This is expected from top-k retrieval and answer-generation interactions, and it argues against a
hard rate threshold as the scientific method.

## Recommended next experiment

Use 0.1% and 0.25% jointly for method development, retain 0.5% as a transition stress test, and
retain 1% and above as the regime where the honest conclusion may be “prefer internal knowledge.”
Do not tune only on 0.25% and then describe it as independent validation.

The next workflow should remain LLM-driven, but give its arbiter stronger observable information:

1. Keep the cached RAG and same-model closed-book verdicts as immutable endpoints.
2. Ask the same model to judge each retrieved passage independently against neutral atomic
   propositions from the original claim. Do not expose poison provenance or the nominal rate.
3. Summarize direct support, direct contradiction, source diversity, near-duplicate support, and
   disagreement across passages. This targets the information bottleneck that defeated the prior
   endpoint-only selectors: coherent poisoned evidence looked persuasive when compressed into one
   RAG rationale.
4. Give an LLM arbiter the two endpoint verdicts and the structured, passage-level checks. Its
   action remains selecting an existing endpoint, which keeps attribution and evaluation clear.
5. Include equal-call direct-answer and claim-only selection controls. A positive result must come
   from using retrieval diagnostics, not merely from spending more inference calls.

Primary results must be per victim with the same model used for RAG, closed-book answering, passage
checks, and arbitration. A secondary panel-assisted variant is valuable, but it must beat the
three-model panel as well as RAG. Suggested development gates are:

- At 0.1% and 0.25%, beat both same-model endpoints for at least two victims while staying within
  one clean claim of clean RAG on the 100-claim development set.
- For the panel-assisted variant, beat both RAG and the 192/227 panel baseline rather than treating
  the weaker same-model endpoint as sufficient.
- At 0.5%, show graceful degradation; at 1%, match the chosen internal baseline rather than forcing
  retrieval use.
- After tuning, freeze prompts, calls, selection rules, rates, and attackers before using fresh
  claims. Current development scores are not confirmation evidence.

Finally, this endpoint scan is diagonal: each victim is paired with poison produced by the same
model. The completed crossed-attacker diagnostic showed that attacker identity is a major
confound. Before a positive claim, repeat the selected low-rate conditions with a predeclared fixed
strong attacker or the full crossed matrix.

## Reproduction artifacts

- Freeze: `configs/stage1_intermediate_rate_scan_freeze.json`
- Protocol and exact commands: `docs/INTERMEDIATE_RATE_SCAN_PROTOCOL.md`
- Progress: `artifacts/runs/progress/stage1_intermediate_rate_scan_v1.json`
- New-rate scan: `artifacts/evaluation/stage1_rag_v1.2_intermediate_rate_scan_v1.json`
- New-rate complementarity: `artifacts/evaluation/stage1_rag_v1.2_intermediate_rate_complementarity_v1.json`
- Combined seven-rate analysis: `artifacts/evaluation/stage1_rag_v1.2_combined_rate_curve_v1.json`
- Scoped audit: `artifacts/runs/stage1/development/rag/stage1_rag_v1.2/intermediate_rate_scan_v1_audit.json`
- Immutable endpoint traces: `artifacts/runs/stage1/development/rag/stage1_rag_v1.2/`

Generated payloads are Git-ignored by design; the tracked protocol, configuration, scripts, and
logs define how to reconstruct and audit them.
