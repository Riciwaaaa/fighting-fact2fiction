# Stage 3 claim-level arbiter v1 results

Status: complete on method-design; **primary success gate failed**; validation remains unopened

Stage 3 v1 uses a Qwen evidence critic followed by either a GLM or Qwen claim-level arbiter. It is
an LLM workflow rather than a fixed decision tree. The arbiter chooses `trust_retrieval`,
`trust_memory`, `synthesize`, or `escalate` and always emits a fallback verdict.

## Completeness and reproducibility

- 318/318 clean-plus-1% packets have evidence critiques.
- 636/636 packet/arbiter pairs have valid outputs (318 per arbiter).
- The final replay produced 636/636 LLM cache hits and 636/636 immutable output reuses.
- The independent audit found no missing/duplicate identity, contract mismatch, raw URL,
  source-origin identifier, condition marker, or gold marker in any referenced prompt.
- A deterministic Qwen typo, `rationate` for `rationale`, is normalized under the explicit
  `v2-qwen-rationate-field-alias` parser contract. No response content is inferred or remapped.
- Prompt-side JSON is now canonicalized. An earlier integration replay exposed that fresh and
  reloaded dictionaries could otherwise produce different cache keys from key order alone.

## Main result

| Arbiter | Clean accuracy | 1% accuracy | 1% RAG | Strongest 1% model-only | Beats both at 1%? |
|---|---:|---:|---:|---:|---:|
| GLM 5.2 | 76.1% | 73.2% | 44.9% | 84.8% (GLM memory) | No |
| Qwen 3.5 35B-A3B | 79.4% | 74.6% | 44.9% | 84.8% (GLM memory) | No |

Both workflows defend substantially better than poisoned RAG, but both are materially worse than
answering the end claim directly with the strongest memory-only model. Therefore Stage 3 v1 is not
a valid proposed defense and must not be evaluated on the 40-claim validation partition.

## Why it failed

At 1%, GLM memory alone is correct on 117/138 pairs. The RAG/GLM-memory oracle is 128/138 = 92.8%,
so useful RAG-only cases exist, but overrides require high precision.

- The GLM arbiter changes the GLM-memory prediction 32 times: 3 gains, 19 regressions, and 10 cases
  where both are wrong.
- The Qwen arbiter changes it 38 times: 8 gains, 22 regressions, and 8 cases where both are wrong.
- Qwen's `trust_retrieval` route is only 8/28 correct; relative to GLM memory it gains 6 cases but
  sacrifices 14.
- GLM's 15 `escalate` fallbacks are only 2/15 correct. Even perfect repair of those 13 errors would
  reach 114/138, still below GLM memory's 117/138.
- Arbiter confidence is not a reliable override signal. Qwen's very-high-confidence overrides have
  3 gains and 15 regressions.
- The retrieval critic is itself fooled by coherent poison. Among Qwen overrides labeled as having
  strong retrieval coverage, there are 4 gains and 15 regressions.

This directly answers an important research question: generic LLM evidence criticism does not
reliably distinguish clean support from coherent poisoned support, even when internal judgments are
shown alongside it.

## Research decision before Stage 4

Do not send every disagreement through proposition checking and do not treat Stage 3's verdict as
the new default. A defensible v2 should be an **anchor-then-challenge LLM workflow**:

1. Use the strongest frozen memory-only endpoint as the default anchor and expose its design-split
   reliability profile explicitly rather than masking all candidate competence.
2. Let an LLM propose an override and the two or three propositions that would justify it, but do
   not let fluent retrieved coherence constitute sufficient support.
3. Invoke Stage 4 on the condition-blind trigger “proposed verdict differs from the anchor” in both
   clean and attacked cases (33 clean and 38 attacked pairs for the current Qwen proposer).
4. Have independent models answer those decisive propositions without retrieval, then use a
   separate deliberator to confirm the anchor or accept the override.
5. On the attacked override subset, Stage 4 must achieve at least 23/38 correct to improve on the
   anchor; this is the next measurable feasibility gate.
6. Freeze v2 on the 60 design claims before opening the 40 validation claims. If it cannot beat the
   anchor, report a characterization/negative result rather than tuning on validation.

Generated sources:

- `artifacts/runs/stage3/stage3_claim_arbiter_v1/private_manifest.json`
- `artifacts/evaluation/stage3_claim_arbiter_v1.json`
- `artifacts/evaluation/stage3_override_diagnostics.json`

