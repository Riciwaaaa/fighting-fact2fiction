# Locked neutral-firewall confirmation

Status: complete negative confirmation result; no post-label method tuning permitted  
Split: 100 balanced binary AVeriTeC claims  
Attack: complete 3-attacker × 3-victim Fact2Fiction matrix at 1%, seed 101  
Models: GLM 5.2, Llama 3.1 70B Instruct, Qwen 3.5 35B-A3B

## Bottom line

The strict same-model neutral-firewall workflow does **not** confirm a defense that outperforms
both model-only and poisoned RAG while preserving clean accuracy. It substantially improves over
poisoned RAG, but model-only remains better overall and the exact-call direct end-claim control is
better still. None of the three victim models passes the frozen practical gate, the strongest-
attacker gate fails, and the method-specificity gate fails.

This is the final result for the frozen workflow. The locked split must not be used to tune another
prompt, semantic predicate, threshold, model choice, attacker panel, or evaluation scope.

## Audited workload

- 300/300 clean RAG endpoints.
- 77 claims clean-correct for all three victims under the Fact2Fiction eligibility convention.
- 693/693 crossed attacked endpoints: 77 claims in every attacker-victim cell.
- 993 attacker-hidden input packets: 300 clean plus 693 attacked.
- 390 RAG/memory disagreement rows and 780/780 Stage 5 row outputs across two variants.
- Pre-label audits passed with no provenance, same-model identity, prompt-isolation, completeness,
  or immutable-output failure.

Four operational amendments were recorded before gold evaluation. The final one maps Qwen claim
264 to the pre-existing memory endpoint after all 15 Stage 5 analysis attempts terminated with
truncated invalid JSON. It applies symmetrically to the proposed workflow and direct control,
retains all four rows, and cannot improve over model-only on those rows. The mandatory exclusion
sensitivity removes the same model/claim endpoint and reaches the same conclusion.

## Primary attacked result

| System | Correct / 693 | Accuracy | Macro-F1 |
|---|---:|---:|---:|
| Poisoned RAG | 396 | 57.14% | 57.04% |
| Same-model closed-book | 561 | 80.95% | 83.73% |
| Exact-call direct deliberation | **563** | **81.24%** | **84.03%** |
| Unconstrained neutral selector | 552 | 79.65% | 81.95% |
| Strict neutral firewall | 554 | 79.94% | 82.66% |

The strict workflow gains 203 cases and loses 45 against poisoned RAG. Against model-only it gains
13 but loses 20, a net loss of seven cases (two-sided exact McNemar `p=0.2962`). Against the
cost-matched direct control it gains nine but loses 18, a net loss of nine (`p=0.1221`). Its
claim-clustered intervals do not establish a model-general positive gain.

The semantic guard helps only marginally: it rejects 14 of the unconstrained selector's 47
retrieval requests and improves attacked accuracy by two cases, while losing three clean cases.

## Same-model victim results

Attacked values aggregate the three equally sized attacker cells. Clean values use all 100 locked
claims. `Δ clean` is strict accuracy minus the stronger clean endpoint.

| Victim | RAG attacked | Memory attacked | Direct attacked | Strict attacked | Best clean endpoint | Strict clean | Δ clean | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| GLM 5.2 | 156/231 | 195/231 | **200/231** | 198/231 | 88/100 RAG | 84/100 | −4 points | Fail |
| Llama 3.1 70B | 123/231 | **180/231** | 179/231 | **180/231** | 84/100 RAG | 67/100 | −17 points | Fail |
| Qwen 3.5 35B-A3B | 117/231 | **186/231** | 184/231 | 176/231 | 88/100 RAG | 79/100 | −9 points | Fail |

GLM is the only victim for which strict beats both attacked endpoints: 198 versus memory 195 and
RAG 156. It nevertheless fails because clean accuracy is four points below clean RAG and because
the direct control reaches 200. Llama ties model-only under attack and defaults to it on every
accepted strict decision, leaving a 17-point clean loss. Qwen loses ten attacked cases relative to
model-only.

The GLM-generated poison gate also fails: strict reaches 181/231 versus model-only at 187/231.
Under Llama-generated poison strict reaches 190 versus memory 187, but this is the weakest attacker
and does not rescue the predeclared full-matrix conclusion.

## Frozen gates

| Criterion | Result |
|---|---|
| Strict beats both attacked endpoints and stays within two clean points, per victim | 0/3 victims pass |
| At least two victims pass | Fail |
| Under GLM poison, strict is non-inferior to model-only | Fail, 181 < 187 |
| Strict beats the exact-call direct control over all attacks | Fail, 554 < 563 |
| All confirmation criteria pass | **Fail** |

Excluding all four Qwen claim-264 rows leaves 690 attacked rows. Strict remains 554 correct versus
memory 561 and direct control 563; every gate remains false.

## What the result says about the mechanism

The bottleneck is not a lack of endpoint complementarity. The attacked endpoint oracle reaches
619/693, leaving 58 correct cases beyond model-only. The problem is selecting them without knowing
whether retrieval is clean or poisoned.

The frozen workflow defaults to memory unless two same-model checks provide unusually strong
retrieval support. On clean data, RAG is 260/300 while memory is 222/300, but strict accepts only 10
of 79 endpoint disagreements. Those 10 switches are precise—nine improve on memory and one hurts—
yet recover too little of clean RAG's advantage. Under attack, 33 accepted retrieval switches
produce only 13 gains and 20 losses. Thus the same signal has low recall when retrieval should be
trusted and insufficient precision when retrieval is poisoned.

The direct end-claim control is at least as important scientifically as the negative method result:
three direct assessments plus the same endpoint selector outperform the neutral subclaim workflow
by nine attacked cases. This does not prove direct answering is universally optimal, but it shows
that the proposed neutral decomposition did not add a defensible, model-general signal beyond
cost-matched end-question deliberation.

## Research decision

Do not present this workflow as a successful poisoning defense. Two defensible workshop paths
remain:

1. **Characterization/negative-result paper.** The broad finding is that parametric knowledge is a
   strong fallback against non-adaptive RAG poisoning, but an endpoint-only same-model LLM
   workflow does not reliably turn endpoint complementarity into a clean-preserving win. The full
   attacker-victim matrix, direct-call control, clean tradeoff, and untouched negative
   confirmation make this a useful empirical result.
2. **New positive-method cycle on fresh data.** Add genuinely independent information: normalized
   retrieved excerpts and diversity/duplication diagnostics, or a cross-family closed-book panel.
   Compare against an equally expensive model-only ensemble. Tune only on a new development split,
   target both clean retrieval-switch recall and attacked switch precision, and confirm once on a
   new held-out dataset. The current locked set may be used only as prior evidence, never as that
   confirmation set.

## Reproducibility

- Frozen protocol: `configs/stage5_locked_confirmation_freeze.json`
- Pre-gold amendments: `configs/stage5_locked_confirmation_amendment_{1,2,3,4}.json`
- Protocol and commands: `docs/LOCKED_CONFIRMATION_PROTOCOL.md`
- Input manifest SHA-256: `4dbf06ba6ef102bbfc3d16db7da0cc41b7677edacb690f4738b8bb2ecc420c49`
- Workflow manifest SHA-256: `580abe028f95fbc7ed7900b14099d901e79a0b3e3819d2881edc7cab188a0328`
- Evaluation SHA-256: `718dbc33ca09dfc1894b22bfcfc849d808b078fb4f8f7676bf1a5452aa7dff86`
- Evaluation artifact: `artifacts/evaluation/stage5_locked_neutral_firewall_v1.json`
