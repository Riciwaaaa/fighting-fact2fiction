# Frozen Stage C validation and reviewer-control results

Status: frozen method evaluated once on `development_validation`; primary attacked-performance
criterion met for Llama 3.1 70B; original locked test remains unopened

## Defensible method claim

The supported claim is deliberately narrow:

> Under the non-adaptive Fact2Fiction attack at a 1% corpus injection rate, a condition-blind,
> same-model workflow can use one retrieval-isolated pivotal-proposition check to select between
> that model's RAG and repeated closed-book endpoints. For Llama 3.1 70B, the frozen workflow
> outperforms both endpoints on held-out eligible attacked claims, at a cost of one clean error.

This is evidence that parametric knowledge can improve poisoned-RAG decisions. It is not evidence
of a certified defense, model-general robustness, adaptive-attack robustness, or clean-data
improvement.

## Frozen workflow

The exact freeze is in `configs/stage4_candidate_freeze.json` and commits to prompt, code, split,
model, seed, and decoding hashes. For every claim:

1. Llama's endpoint-only router sees its RAG endpoint and its three-repeat closed-book endpoint.
2. If the verdicts agree, the common verdict is copied with no Stage C call.
3. If they disagree, the router's pivotal proposition is checked in a fresh closed-book context
   that sees no endpoint or retrieved passage.
4. A final same-model call selects the RAG or memory endpoint; it cannot create a third verdict.

The attack condition is never an input. The same activation is used for clean and attacked rows.
Inference audits verify same-model identity, immutable cache/output identities, endpoint-copy
semantics, and the absence of gold, attack markers, raw URLs, and source-origin markers.

## One-shot validation result

The validation partition contains 40 clean claims. Fact2Fiction's model-specific second eligibility
filter leaves 28 Llama claims for the attacked condition.

| Validation condition | RAG | Same-model closed-book | Router | Frozen targeted Stage C |
|---|---:|---:|---:|---:|
| Clean | **28/40 (70.0%)** | 20/40 (50.0%) | 26/40 (65.0%) | 27/40 (67.5%) |
| Fact2Fiction 1% | 21/28 (75.0%) | 16/28 (57.1%) | 21/28 (75.0%) | **23/28 (82.1%)** |

At 1%, Stage C has seven paired gains and zero regressions relative to same-model closed-book
(two-sided exact McNemar p=0.0156). Relative to poisoned RAG it has three gains and one regression
(p=0.625). Thus it clearly beats the user-requested model-only baseline on this split, while the
increment over RAG is positive but too small for significance by itself.

Clean Stage C is one example below RAG. This is a 2.5-point loss on 40 cases and narrowly misses the
literal two-point gate even though it is the smallest possible nonzero loss after one case. It must
be reported as a small robustness/utility tradeoff, not as clean-accuracy preservation under the
original threshold.

## Exact-budget generic-check control

After the frozen validation run, an additional fixed ablation replaced every selected pivotal
proposition with the repository's existing generic fallback: “Whether the original claim's central
factual assertion is accurate as stated.” Activation, endpoint packet, router metadata, check
prompt, final selector, seeds, and two-call disagreement budget were otherwise identical. It was
defined before examining its outputs but, because it was added after validation gold was opened,
it is a transparent post-validation ablation rather than a preregistered confirmatory test.

| Split / condition | Generic end-claim control | Targeted proposition |
|---|---:|---:|
| Method-design clean | **44/60** | 43/60 |
| Method-design 1% | **36/44** | 35/44 |
| Validation clean | **29/40** | 27/40 |
| Validation 1% | 21/28 | **23/28** |

On validation attack, targeting gives two paired gains and zero regressions over the exact-budget
generic control (p=0.5). On validation clean, the generic control gives two gains and zero
regressions. The defensible interpretation is not that proposition targeting dominates direct
checking everywhere: it trades two clean cases for two attacked cases on validation. Importantly,
extra generic deliberation alone does not reproduce the held-out attacked gain; it ties poisoned
RAG at 21/28.

The preregistered seven-call v2 control is even stronger in call budget: five direct end-claim
answers, one isolated synthesis, and one firewalled selector. On method-design attack it reaches
32/44, below both targeted Stage C (35/44) and proposition v2 (34/44). Proposition v2 is retained as
a negative design result because its 38/60 clean score fails the clean gate.

## Pooled development evidence

Pooling the disjoint 60 design and 40 validation claim groups is descriptive, not a second
confirmatory test:

| Condition | RAG | Closed-book | Generic control | Targeted Stage C |
|---|---:|---:|---:|---:|
| Clean | **72/100 (72.0%)** | 54/100 (54.0%) | **73/100 (73.0%)** | 70/100 (70.0%) |
| Fact2Fiction 1% | 50/72 (69.4%) | 47/72 (65.3%) | 57/72 (79.2%) | **58/72 (80.6%)** |

For the pooled attacked rows, targeted Stage C has 13 gains versus two regressions over model-only
(p=0.00739) and ten gains versus two regressions over poisoned RAG (p=0.0386). Pooled clean is
exactly two points below RAG. These pooled tests support workshop-level evidence but do not erase
the small validation denominator or method-selection history.

## Why the method is reviewer-defensible

- **The primary comparison is same-model.** RAG, model-only, router, checker, and selector all use
  Llama 3.1 70B; no stronger cross-model judge is hidden in the workflow.
- **The checker is retrieval-isolated.** Poisoned passages and endpoint rationales cannot directly
  determine its judgment.
- **The output space is controlled.** The final call selects an existing endpoint, separating
  routing from unrestricted answer generation.
- **The activation is condition-blind.** Endpoint disagreement triggers Stage C in clean and
  attacked conditions alike.
- **The main result replicates on held-out claims.** The frozen attacked score remains above both
  endpoints, with a significant paired gain over model-only.
- **The direct-deliberation alternative is measured.** A structurally identical two-call generic
  control does not match targeted Stage C on validation attack; a seven-call direct control also
  remains below it on method-design.
- **Negative evidence is retained.** Qwen and GLM fail the original same-model design gate, and the
  firewalled seven-call redesign fails clean utility. The claim remains model-conditional.

## Limitations and next experiments

The study has only 28 held-out attacked Llama rows. The validation improvement over RAG and the
targeting improvement over the generic control are not individually significant. The final
selector still re-reads endpoint rationales, so coherent poison can override a correct internal
signal; claims 202 and 489 are known method-design examples. Conversely, the rationale firewall in
v2 prevents re-poisoning but causes excessive clean abstention. The present method is an empirical
accuracy defense, not an information-flow guarantee.

The current evidence covers one model and one non-adaptive 1% rate. The next paper experiments
should keep all prompts frozen and add: the 0.1%, 4%, and 8% rate curve; a larger claim set or locked
test; at least one adaptive attacker that targets common parametric beliefs; a targeted-versus-
generic control declared before inference; calibration/coverage reporting; and secondary
multi-model checkers reported separately from the same-model primary claim.

## Reproduction and artifacts

```bash
PYTHONPATH=src python3 scripts/check_aligned_router.py \
  --run-root artifacts/runs/stage3/stage3_same_model_validation_v1
PYTHONPATH=src python3 scripts/check_aligned_verification.py \
  --run-root artifacts/runs/stage4/stage4_same_model_validation_v1
PYTHONPATH=src python3 scripts/check_aligned_verification.py \
  --run-root artifacts/runs/stage4/stage4_generic_control_validation_v1
PYTHONPATH=src python3 scripts/summarize_stage4_final.py
```

The consolidated gold-joined metrics, paired tests, per-disagreement records, action profiles, and
token/latency accounting are in `artifacts/evaluation/stage4_final_study.json`. Raw requests and
responses remain content-addressed under `artifacts/cache/llm/`; run manifests and progress logs
remain under `artifacts/runs/`.
