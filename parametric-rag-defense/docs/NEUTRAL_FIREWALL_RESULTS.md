# Neutral firewalled workflow: development results

## Outcome

The frozen unconstrained workflow did **not** pass its preregistered gate. A post-label audit then
identified a narrow implementation defect: the final prompt explicitly allowed retrieval only when
both retrieval-isolated checks converged on the retrieval endpoint's label using direct factual
support, but the JSON validator did not enforce that semantic condition. The LLM violated the full
condition in 20 of its 28 attacked retrieval requests.

Applying the already-written policy as a deterministic safety contract, without any new model
calls, produces the desired development signal:

- 423/549 (77.0%) across attacked rows, versus 417/549 (76.0%) same-model closed-book,
  416/549 (75.8%) exact-call direct deliberation, and 320/549 (58.3%) poisoned RAG;
- 7 paired wins and 1 loss versus closed-book (exact McNemar p=0.0703);
- 8 paired wins and 1 loss versus the direct control (p=0.0391);
- 140/183 under the strongest GLM attacker, versus 139/183 closed-book and 72/183 RAG;
- the practical per-victim gate passes for GLM and Qwen, but not Llama because Llama's clean RAG
  endpoint is much stronger than its closed-book endpoint.

This corrected result is **exploratory, not confirmatory**. The missing validator was diagnosed
after development labels were opened. Its legitimacy comes from implementing an exact condition in
the pre-output frozen prompt, not from being selected blind to outcomes. It must be confirmed once
on untouched held-out claims before serving as a paper headline.

## What was run

The experiment covers 300 clean rows and the complete 549-row 1% crossed attacker-victim matrix.
For each endpoint disagreement, the victim model itself performs every additional role:

1. write a claim-only neutral proposition plan before seeing either endpoint;
2. make a supportive but calibrated retrieval-isolated assessment;
3. make a skeptical retrieval-isolated counter-assessment;
4. see only the two endpoint labels and the internal bundle, then select one endpoint.

No selector sees retrieved passages, RAG rationale, endpoint confidence/coverage, attacker identity,
condition, or gold. The exact-call control replaces the neutral plan and two checks with three fresh
direct claim assessments and uses the same final selector. Both variants use four logical calls per
disagreement. Reused inputs reduced the maximum fresh calls to 766 per variant: 186 plans, 372
neutral checks, 558 direct checks, and 416 unique selectors, or 1,532 calls total.

All calls completed. The pre-label audit found 714/714 expected row-level outputs, 416/416 unique
selectors, zero inference failures, and zero privacy, contract, provenance, or completeness failure.

## Frozen unconstrained result

The first table is the literal output of the frozen LLM selector, before semantic enforcement.

| Victim | Attacked neutral | Closed-book | Poisoned RAG | Direct control | Clean neutral | Best clean endpoint | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| GLM 5.2 | **159/183** | 153 | 124 | 153 | **82/100** | 82 | pass |
| Llama 3.1 70B | 120/183 | **120** | 98 | **120** | 55/100 | **72** | fail |
| Qwen 3.5 35B-A3B | 136/183 | **144** | 98 | 143 | 70/100 | **73** | fail |

Overall attacked accuracy is 415/549, two cases below closed-book and one below direct control. Under
GLM-generated poison it is 135/183, below closed-book's 139/183. Thus the frozen gate correctly
fails.

The failure is highly structured. On attacked disagreements, the selector chose retrieval in all
10 cases where the supportive check said `Supported` and the skeptical check said `Refuted`. All
10 selections were wrong. This directly contradicts the frozen instruction that the assessments
must converge on retrieval. The original audit checked prompt isolation and output shape, but not
this semantic invariant.

## Policy-enforced exploratory result

The correction retains the complete LLM workflow and adds one necessary-condition guard:

```text
accept retrieval only if
  the selector requests retrieval, and
  support_check.verdict == retrieval_label, and
  counter_check.verdict == retrieval_label, and
  both checks cite nonempty direct-recall factual propositions;
otherwise select memory.
```

The guard uses no gold, attack indicator, threshold, RAG rationale, or retrieved text and never
synthesizes a verdict. It is not a replacement decision tree: the model still defines the plan,
produces both factual assessments, and selects an endpoint. The guard makes the model obey the
workflow's predeclared safety condition.

| Victim | Strict attacked | Closed-book | Poisoned RAG | Direct control | Strict clean | Best clean endpoint | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| GLM 5.2 | **156/183** | 153 | 124 | 153 | 81/100 | **82** | pass |
| Llama 3.1 70B | 120/183 | **120** | 98 | **120** | 54/100 | **72** | fail |
| Qwen 3.5 35B-A3B | **147/183** | 144 | 98 | 143 | 72/100 | **73** | pass |

The strict workflow beats both attacked endpoints for GLM and Qwen and ties Llama closed-book. Its
two-victim practical gate passes for GLM and Qwen: both beat the stronger attacked endpoint and stay
within two clean points of the stronger clean endpoint. Qwen's clean loss is one point.

The point estimates are encouraging but small. Claim-clustered 95% bootstrap intervals for the
strict-minus-closed-book attacked accuracy delta are `[0.000, 0.049]` for GLM,
`[0.000, 0.000]` for Llama, and `[-0.011, 0.055]` for Qwen. Across all victims and attackers the
clustered interval is `[-0.002, 0.029]`. These intervals do not establish a strictly positive
model-general effect.

## Attacker-victim breakdown

Each cell has 61 claims. Entries are `strict / closed-book / poisoned RAG`; attacker is the row and
victim is the column.

| Attacker | GLM victim | Llama victim | Qwen victim |
|---|---:|---:|---:|
| GLM | 52 / 51 / 28 | 40 / 40 / 22 | 48 / 48 / 22 |
| Llama | 52 / 51 / 54 | 40 / 40 / 47 | 50 / 48 / 49 |
| Qwen | 52 / 51 / 42 | 40 / 40 / 29 | 49 / 48 / 27 |

The method is robust to the strongest attacker in aggregate, but does not win every cell. In
particular, clean and Llama-attacker RAG are often good enough that a memory-fallback defense gives
up utility. This is the remaining information problem: with attacker identity hidden, the workflow
must distinguish useful clean/weakly attacked retrieval from coherent poison using only independent
parametric evidence.

## Mechanistic interpretation

The unconstrained selector requested retrieval 28 times on attacked disagreements. The strict
contract accepts only 8; 7 repair a closed-book error and 1 replaces a correct closed-book answer.
Retrieval-switch precision therefore rises from 42.9% to 87.5%, while recall of the 58 available
retrieval-only rescues falls from 20.7% to 12.1%. This is a sensible defense tradeoff at 1% poison:
high precision matters because closed-book is already the stronger aggregate endpoint.

The direct-deliberation control requests retrieval only once on attacked rows and gets it wrong.
Thus the gain is not explained by spending four more same-model calls or majority-like
self-consistency alone. The neutral proposition plan plus two opposed checks exposes a small set of
high-precision rescue cases. Conversely, unconstrained natural-language policy compliance is not
reliable enough; a typed semantic guard is part of the method.

## Required confirmation plan

1. Freeze the exact prompts, four-call workflow, semantic predicate, model endpoints, 1% poisoning
   construction, attacker panel, decoding, and all reporting code. Do not tune by model.
2. Run once on untouched binary held-out claims. Recompute clean endpoints and a complete crossed
   attacker-victim matrix on the jointly eligible subset; cache every intermediate artifact.
3. Use per-victim attacker-aggregated strict accuracy as primary. The preregistered practical gate
   remains: beat both same-model endpoints under attack and lose no more than two clean points, for
   at least two victims.
4. Retain the exact-call direct control and report all nine attacker-victim cells, paired tests,
   claim-clustered intervals, retrieval-switch precision/recall, and strongest-attacker results.
5. If the strict result fails held-out confirmation, report the development result as hypothesis
   generation. Do not introduce another rule on the locked outcomes.

The immutable original result is in
`artifacts/evaluation/stage5_neutral_firewall_v1.json`; the post-label diagnostic is in
`artifacts/evaluation/stage5_neutral_firewall_diagnostic_v1.json`; and the policy-enforced
exploratory summary is in `artifacts/evaluation/stage5_neutral_firewall_strict_v1.json`.
