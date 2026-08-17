# Stage 1 clean RAG and poisoning-scan results

Date: 2026-08-09 (America/Los_Angeles)

These are development-set signal-finding results, not a final defense evaluation. The locked split
has not been opened. The exact preliminary approximations are recorded in
`STAGE1_RAG_SCAN_PROTOCOL.md`.

## Coverage and integrity

- Dataset: 100 balanced binary AVeriTeC development claims (50 Supported, 50 Refuted).
- Evidence: official AVeriTeC development knowledge store, SHA-256
  `021e258cd6fb5fe6d627a4667d663e95c184c966939c15124df9206142fc2212`.
- Selected clean pools: 81,326 documents; mean 813.26, median 774.5, range 306--1,338.
- Victims: Llama 3.1 70B Instruct, Qwen 3.5 35B-A3B, and GLM 5.2.
- Clean endpoints: 300/300. Fact2Fiction clean-correct eligibility: 234 victim/claim pairs.
- Attacked endpoints: 936/936 (234 pairs at each of four rates).
- Audit: 1,236/1,236 expected normalized endpoints; no missing, unexpected, noncanonical, or
  poison-material failures.
- Reusable model work referenced by this scan: 2,981 unique cached responses, 8,793,629 prompt
  tokens and 968,083 completion tokens.

The 60 pre-v1.1 smoke endpoints and traces were moved to
`artifacts/runs/stage1/development/history/pre_v1.1_smoke/`; they are not included in any result.

## Clean baselines

The model-only value is the majority of three cached decoding seeds. Clean RAG uses the frozen
single-seed InFact-style workflow. These values use all 100 claims.

| Victim | Model-only accuracy | Clean RAG accuracy | Clean-correct attacked pairs |
|---|---:|---:|---:|
| Llama 3.1 70B | 54% | 73% | 73 |
| Qwen 3.5 35B-A3B | 73% | 78% | 78 |
| GLM 5.2 | 80% | 83% | 83 |
| Micro-average | 69% | 78% | 234 |

## Initial four-level scan

All values below are micro-averages over the 234 clean-correct victim/claim pairs. Thus the
poisoned-RAG accuracy is also `1 - attack success rate`. Model-only values are recomputed on this
same filtered subset and must not be confused with the full-development values above.

| Nominal rate | Mean realized rate | Poison among retrieved evidence | Poisoned RAG | Attack success | Same-victim internal | Three-model internal majority | Same-victim oracle | RAG + any-internal oracle |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.1% | 0.131% | 5.21% | 82.05% | 17.95% | 77.35% | 84.62% | 96.15% | 98.72% |
| 1% | 0.939% | 43.66% | 58.97% | 41.03% | 77.35% | 84.62% | 90.60% | 97.86% |
| 4% | 3.938% | 84.93% | 32.48% | 67.52% | 77.35% | 84.62% | 82.91% | 95.30% |
| 8% | 7.943% | 92.82% | 26.07% | 73.93% | 77.35% | 84.62% | 81.62% | 94.87% |

The Wilson 95% intervals for poisoned-RAG accuracy are respectively 76.63--86.44%, 52.58--65.08%,
26.80--38.72%, and 20.86--32.05%. These intervals are descriptive: victim/claim observations are
not fully independent because a claim may be eligible for more than one victim.

### Per-victim poisoned-RAG accuracy

| Victim | Eligible pairs | 0.1% | 1% | 4% | 8% | Same-victim internal on eligible pairs |
|---|---:|---:|---:|---:|---:|---:|
| Llama 3.1 70B | 73 | 90.41% | 80.82% | 53.42% | 50.68% | 65.75% |
| Qwen 3.5 35B-A3B | 78 | 73.08% | 42.31% | 17.95% | 11.54% | 80.77% |
| GLM 5.2 | 83 | 83.13% | 55.42% | 27.71% | 18.07% | 84.34% |

## What this establishes

The broad research question is valid at a workshop signal-finding level.

1. The attack produces a clear aggregate dose response. A 0.94% realized corpus fraction becomes
   43.66% of retrieved evidence; at 3.94%, poisoned evidence occupies 84.93% of retrieval slots.
   Poisoned-RAG accuracy correspondingly falls from 82.05% at the weakest level to 26.07% at 8%.
2. Internal knowledge is useful but is not a universally superior replacement for retrieval. At
   0.1%, poisoned RAG beats the same victim's model-only answer (82.05% versus 77.35%). At 1% and
   above, the ordering reverses. Llama remains much more robust than its own weak model-only
   baseline, whereas Qwen and GLM show the opposite pattern under stronger attack.
3. There is substantial exploitable complementarity. At 1%, same-victim internal knowledge alone
   rescues 74 cases where poisoned RAG is wrong, while RAG alone rescues 31 internal errors. These
   counts become 118 versus 13 at 4%, and 130 versus 10 at 8%. A gold oracle combining the two
   reaches 90.60%, 82.91%, and 81.62% at those levels.
4. Multi-model signals add further headroom. A fixed three-model internal majority is 84.62% on
   the paired subset, while an oracle allowed to choose RAG or any internal endpoint remains
   94.87--98.72% accurate across the curve.

The oracle is diagnostic only. It does **not** show that a deployable defense already beats both
poisoned RAG and model-only. It shows that the cached endpoints contain enough complementary signal
for an LLM workflow to try. The required Stage 3 result remains a gold-blind selector that exceeds
both standalone endpoints on the same paired claims.

## Limitations before a paper claim

- This is one development split, one attack seed, and one RAG decoding seed. It is suitable for
  method design, not confirmatory testing.
- The attacker is victim-aware but not adaptive to the future defense.
- Up to 12 independently generated poison blueprints are deterministically expanded to the exact
  corpus budget. Publication results should generate every poison document independently and run
  an exact-upstream sensitivity condition.
- Question answering is batched rather than using the upstream result-by-result loop.
- Fact2Fiction's second eligibility filter is applied separately per victim, so per-model rows have
  different claim subsets. Cross-model tests should group or bootstrap by claim.
- Model-only uses a three-seed majority while RAG currently uses one decoding seed. This is useful
  for a stable signal scan but should be equalized or explicitly ablated in the primary study.

## Decision for the next stage

Proceed to Stage 3 on development data, but keep the claim narrow: learn or prompt a gold-blind LLM
workflow that arbitrates between the end-question model-only verdict and the RAG trace. Use
subquestion-level internal answers as optional diagnostics or escalation evidence, not as the sole
defense. Report same-model and multi-model variants. Freeze the workflow and thresholds before
opening the locked split; the primary gate is accuracy above both poisoned RAG and model-only at
prespecified attack levels while retaining clean-RAG accuracy.

Machine-readable results are in
`artifacts/evaluation/stage1_fact2fiction_initial_scan.json` and
`artifacts/evaluation/stage1_endpoint_complementarity.json`; the integrity record is
`artifacts/runs/stage1/development/rag_scan_audit.json`.
