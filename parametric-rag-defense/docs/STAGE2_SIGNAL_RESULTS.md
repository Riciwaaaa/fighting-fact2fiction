# Stage 2 signal characterization

Status: complete on the 60-claim method-design partition; validation remains unopened

The frozen Stage 2 split contains 60 balanced method-design claims and 40 balanced one-shot
development-validation claims. All models, attack strengths, and seeds for a claim remain grouped.
Only the 60 design claims were used here.

## Sanitized packet corpus

- 732/732 expected packets were built: 180 clean and 138 at each of four attack strengths.
- All packet and source RAG task keys are unique.
- Packets expose only claim/date, normalized retrieval assessment, and identity-masked repeated
  memory-only assessments.
- Gold, correctness, attack condition/strength, poison counts, model/provider identity, raw URLs,
  and source-origin IDs are excluded from the inference-visible object.
- The independent packet audit has no validation failure.

## Design-split signal

| Condition | Pairs | RAG | Same-victim memory | Memory ensemble | RAG + ensemble oracle |
|---|---:|---:|---:|---:|---:|
| Clean | 180 | 76.7% | 68.9% | 76.7% | 89.4% |
| 0.1% | 138 | 81.2% | 78.3% | 83.3% | 98.6% |
| 1% | 138 | 44.9% | 78.3% | 83.3% | 92.0% |
| 4% | 138 | 31.2% | 78.3% | 83.3% | 87.7% |
| 8% | 138 | 21.7% | 78.3% | 83.3% | 85.5% |

At 1%, RAG and the ensemble are both correct on 50 pairs, only RAG is correct on 12, only memory
is correct on 65, and neither is correct on 11. This is useful complementarity, but its base rate is
asymmetric: a switch away from memory must be conservative because memory-only successes greatly
outnumber RAG-only successes.

Generated sources:

- `artifacts/runs/stage2/stage2_signal_v1/manifest.json`
- `artifacts/evaluation/stage2_signal_v1.json`

