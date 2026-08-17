# Fact2Fiction 1% crossed attacker-victim diagnostic

This diagnostic separates poison-generator strength from victim sensitivity. It was frozen before
collection and uses the 61 development claims that pass the clean-correct eligibility filter for
all three victims. Every attacker contributes its already generated poison documents; every victim
uses the unchanged RAG planning, retrieval, question-answering, and verdict pipeline. The three
diagonal cells are the original same-model outputs, and all six off-diagonal cells are new.

The final matrix contains 549/549 expected rows, including 366 new off-diagonal endpoints, with no
runtime or audit failure.

## RAG accuracy

Rows are poison generators and columns are RAG victims. Every cell has 61 identical claims.

| Attacker → / Victim ↓ | GLM 5.2 | Llama 3.1 70B | Qwen 3.5 35B |
|---|---:|---:|---:|
| **GLM 5.2 poison** | 28/61 (45.9%) | 22/61 (36.1%) | 22/61 (36.1%) |
| **Llama poison** | 54/61 (88.5%) | 47/61 (77.0%) | 49/61 (80.3%) |
| **Qwen poison** | 42/61 (68.9%) | 29/61 (47.5%) | 27/61 (44.3%) |

The attacker macro attack-success rates are 60.7% for GLM poison, 46.4% for Qwen poison, and only
18.0% for Llama poison. Holding the victim fixed and replacing GLM poison with Llama poison changes
26 GLM-victim cases, 25 Llama-victim cases, and 27 Qwen-victim cases. The paired exact McNemar
`p`-values are respectively `2.98e-8`, `4.17e-7`, and `1.40e-6`.

By contrast, victim macro accuracy averaged across all attackers is 67.8% for GLM and 53.6% for
both Llama and Qwen. The descriptive attacker macro-accuracy range is 42.6 points, versus a
14.2-point victim range. These are fixed-model descriptive ranges, not population variance
components, but they make the confounding direction clear.

## Poison retrieval exposure

| Attacker → / Victim ↓ | GLM 5.2 | Llama 3.1 70B | Qwen 3.5 35B |
|---|---:|---:|---:|
| **GLM 5.2 poison** | 45.9% | 41.4% | 44.2% |
| **Llama poison** | 28.0% | 36.2% | 30.0% |
| **Qwen poison** | 34.0% | 34.3% | 45.6% |

GLM poison obtains the highest mean retrieval share (43.8%), Llama the lowest (31.4%), and Qwen is
intermediate (38.0%). Retrieval exposure explains part of the attacker effect. It is not the whole
story: 59–61 claims per cell retrieve at least one poison document, yet exposed-claim accuracy
still ranges from 36.1% to 88.1%. Poison content quality and its interaction with the victim matter
after retrieval.

## Endpoint headroom for a defense

The same victim's frozen three-repeat closed-book endpoint is joined only during offline
evaluation. “Oracle” is correct when either RAG or closed-book is correct.

| Attacker | Victim | RAG | Closed-book | Endpoint oracle | Headroom above stronger endpoint |
|---|---|---:|---:|---:|---:|
| GLM | GLM | 28 | 51 | 55 | +4 |
| GLM | Llama | 22 | 40 | 44 | +4 |
| GLM | Qwen | 22 | 48 | 51 | +3 |
| Llama | GLM | 54 | 51 | 60 | +6 |
| Llama | Llama | 47 | 40 | 54 | +7 |
| Llama | Qwen | 49 | 48 | 58 | +9 |
| Qwen | GLM | 42 | 51 | 57 | +6 |
| Qwen | Llama | 29 | 40 | 44 | +4 |
| Qwen | Qwen | 27 | 48 | 52 | +4 |

All nine cells retain at least three recoverable cases, so a selector can in principle beat both
endpoints everywhere. The GLM-attacker cells are much harder: RAG collapses and only three or four
oracle cases remain above strong model-only. Llama-attacker cells are easier but represent the
weakest generator in this pool.

## What caused the original diagonal behavior?

- **GLM's poor same-model poisoned RAG is primarily an attacker-strength effect.** GLM is the most
  robust victim on average, reaching 88.5% under Llama poison, but its own poison generator is the
  strongest and drives its diagonal accuracy to 45.9%.
- **Llama's strong diagonal is primarily a weak-attacker effect, not intrinsic victim resistance.**
  Llama falls from 77.0% under its own poison to 36.1% under GLM poison.
- **Qwen's poor diagonal reflects both sides.** Its poison generator is substantially stronger
  than Llama's, while the Qwen victim is also less robust than GLM under Qwen-generated poison.

Therefore, the earlier diagonal comparison confounded attacker and victim. It is not defensible to
select Llama poison solely because it makes blending easier. A workshop paper should keep the
same-model diagonal as one convention, add a fixed-attacker or full crossed evaluation, and report
all cells. A strong-attacker aggregate or attacker-held-out evaluation is the appropriate next test
of an attack-source-blind arbitration workflow.

## Audited artifacts

- Protocol: `docs/RATE_EXTENSION_PROTOCOL.md`
- Execution freeze: `configs/crossed_av_execution_freeze.json`
- Manifest and immutable outputs:
  `artifacts/runs/stage1/development/rag/stage1_crossed_av_1pct_v1/`
- Progress ledger: `artifacts/runs/progress/stage1_crossed_av_1pct_v1.events.jsonl`
- Evaluation with paired and exposure-conditioned diagnostics:
  `artifacts/evaluation/stage1_crossed_av_1pct_v1.json`

The audit verifies all nine 61-row cells, source poison hashes, attacker/victim identities,
victim-model API calls, condition consistency, and prompt isolation. It reports zero failure.
