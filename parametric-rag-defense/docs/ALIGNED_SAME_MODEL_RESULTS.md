# Strict same-model A/B/C method-design results

Status: complete and audited on the 60-claim method-design partition; **Llama passes the practical
design gate after Stage C**; frozen validation is now complete and reported in
`docs/STAGE4_FINAL_RESULTS.md`

## What was tested

For every row, the RAG victim, three-repeat closed-book endpoint, router, proposition checker, and
final selector use the same model. No router sees another model's answer. All Stage 1 endpoints are
reused from cache.

- A/B source rows: 318 = 180 clean plus 138 model-specific eligible 1% attacked rows.
- A/B calls: 636 = 318 endpoint-only + 318 evidence-aware routers.
- Stage C activation: all 136 endpoint disagreements in the endpoint-only variant, in both clean
  and attacked conditions.
- Stage C calls: 136 closed-book checks + 136 final selectors.
- Replay: 636/636 A/B and 272/272 Stage C calls were cache hits; every immutable output was reused.
- Audits: no missing/duplicate output, contract or identity mismatch, wrong-model request, raw URL,
  source-origin marker, attack-condition marker, or gold marker.

At the time of this method-design run, the 40-claim development-validation partition and original
locked test were not opened. Validation was opened only after the later freeze manifest was
written; the original locked test remains unopened.

## A/B results

The values below are exact correct counts; clean denominators are 60, while attacked denominators
are model-specific because Fact2Fiction eligibility is model-specific.

| Model | Condition | RAG | Closed-book | A: endpoint only | B: all top-k evidence | Oracle |
|---|---|---:|---:|---:|---:|---:|
| GLM 5.2 | Clean | 49/60 | 47/60 | 49/60 | 50/60 | 54/60 |
| GLM 5.2 | 1% | 17/49 | 42/49 | 31/49 | 39/49 | 45/49 |
| Llama 3.1 70B | Clean | 44/60 | 34/60 | 39/60 | 39/60 | 47/60 |
| Llama 3.1 70B | 1% | 29/44 | 31/44 | **34/44** | 31/44 | 38/44 |
| Qwen 3.5 35B | Clean | 45/60 | 43/60 | 47/60 | 48/60 | 53/60 |
| Qwen 3.5 35B | 1% | 16/45 | 35/45 | 26/45 | 29/45 | 38/45 |

Main observations:

- Llama endpoint-only reaches 77.3% at 1%, above Llama closed-book at 70.5% and RAG at 65.9%. It
  recovers 3 RAG-only cases and sacrifices no memory-only cases. However, clean accuracy is 65.0%,
  five cases below clean RAG, so A alone fails the clean gate.
- Adding all top-k excerpts does not solve the problem uniformly. It improves GLM by 8 attacked
  cases and Qwen by 3, but both remain below their closed-book endpoints. It reduces Llama by 3.
- The bottleneck is therefore not simply “too little evidence.” Broader poisoned evidence can help
  expose contradictions for some models, but it can also remove the conservative behavior that
  produced Llama's attacked gain.

Stage C uses endpoint-only: neither Llama A/B variant meets the clean gate, their clean scores tie,
and endpoint-only has the stronger Llama attacked score and exposes less poisoned content. This is
a method-design choice and is now frozen before development-validation.

## Stage C result

Stage C independently checks one pivotal proposition closed-book and then selects an existing
endpoint. It runs only on endpoint disagreements, but the same activation is applied to clean and
attacked rows.

| Model | Clean RAG | Clean closed-book | Clean Stage C | 1% RAG | 1% closed-book | 1% Stage C | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| GLM 5.2 | 49/60 | 47/60 | 49/60 | 17/49 | 42/49 | 38/49 | Fail |
| **Llama 3.1 70B** | **44/60** | 34/60 | **43/60** | 29/44 | 31/44 | **35/44** | **Pass** |
| Qwen 3.5 35B | 45/60 | 43/60 | 41/60 | 16/45 | 35/45 | 33/45 | Fail |

For Llama:

- At 1%, Stage C is 35/44 = 79.5%, versus closed-book 31/44 = 70.5% and RAG 29/44 = 65.9%.
- On clean data it is 43/60 = 71.7%, one case (1.67 points) below clean RAG, satisfying the
  predeclared two-point clean-loss gate.
- Relative to closed-book at 1%, it has 6 Stage-C-only wins and 2 closed-book-only wins, a net gain
  of four cases. It recovers six RAG-only cases while sacrificing two memory-only cases.
- Relative to endpoint-only Stage A, it gains one net attacked case and repairs four net clean
  cases.
- It closes 4/7 of the attacked cases between the stronger endpoint (31) and the endpoint oracle
  (38), reaching 35.

This is the requested practical signal on method-design: for one model, the same-model workflow
beats both same-model endpoints under poisoning and stays within the clean-loss budget.

## Statistical and methodological limitations

The positive result is not yet confirmatory. Against Llama closed-book at 1%, the exact paired
McNemar result is 6 gains versus 2 regressions, two-sided (p=0.289). Against Llama RAG it is 7 gains
versus 1 regression, (p=0.0703). The sample contains only 44 attacked Llama rows, so the effect is
too imprecise for a strong effectiveness claim.

The router also failed to emit a concrete proposition on 15/136 disagreements: 14 Llama cases and
one Qwen case. These are auditably represented as generic closed-book checks of the original claim,
not mislabeled as proposition-level checks. For Llama the fallback counts are 11/25 clean and 3/22
attacked disagreements. A future contract should require a non-empty neutral proposition whenever
endpoint verdicts differ and should compare targeted checks against cost-matched additional
claim-level deliberation.

Qwen and GLM do not support a model-general claim. Stage C improves their endpoint-only attacked
routers, but it remains below their strong closed-book baselines; Qwen also loses substantial clean
accuracy. The current positive claim must remain explicitly model-conditional.

## Poisoning-rate implication

The user's concern about the endpoint gap is correct for GLM and Qwen at 1%: routing must be nearly
perfect because the RAG endpoint is much weaker. Cached 0.1% endpoints provide a more balanced and
larger selection opportunity:

| Model | 0.1% RAG | Closed-book | Oracle | Recoverable cases above stronger endpoint |
|---|---:|---:|---:|---:|
| GLM 5.2 | 36/49 | 42/49 | 47/49 | 5 |
| Llama 3.1 70B | 39/44 | 31/44 | 44/44 | 5 |
| Qwen 3.5 35B | 37/45 | 35/45 | 44/45 | 7 |

At 4% and 8%, Qwen's endpoint oracle equals its closed-book endpoint, and GLM has only one or zero
recoverable cases. No endpoint router can strictly beat closed-book there without generating new
correct information. Llama retains 5 and 4 recoverable cases, respectively.

The next rate experiment should therefore apply the now-frozen endpoint-only + Stage C workflow to
0.1% before changing prompts. This is a robustness-curve measurement, not post-hoc prompt tuning.

## Generated sources

- `artifacts/runs/stage3/stage3_same_model_ab_v1/private_manifest.json`
- `artifacts/evaluation/stage3_same_model_ab_v1.json`
- `artifacts/runs/stage4/stage4_same_model_c_v1/private_manifest.json`
- `artifacts/evaluation/stage4_same_model_c_v1.json`
- `artifacts/runs/progress/stage3_same_model_ab_v1.events.jsonl`
- `artifacts/runs/progress/stage4_same_model_c_v1.events.jsonl`
