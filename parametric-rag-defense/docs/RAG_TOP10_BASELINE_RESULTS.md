# Top-10-per-subquestion RAG baseline results

## Bottom line

Doubling the ordinary retrieval budget improves RAG, but it does not explain the performance of the
internal-knowledge defense. Over the exact 1,260 attacked confirmation rows, top-10 RAG reaches
**53.33%**, compared with 48.97% for top-5 RAG, 73.02% for three-call same-model closed book,
80.16% for the answerability-aware fallback, and 80.48% for the frozen proposed method.

This is an opened-confirmation diagnostic, not independent validation: the 100 confirmation claims
and prior outcomes were already available when this baseline was requested. The protocol was
nonetheless frozen before any top-10 endpoint call, and all systems are compared on identical rows.

## Experimental control

The baseline reuses the exact original question plans, same-model Fact2Fiction poison documents and
embeddings, condition prefixes, victim models, prompts, decoding, evidence truncation, and original
top-5 clean-correct eligibility. It changes only the retrieved documents per subquestion from five
to ten. The top-10 endpoint never receives a closed-book answer, answerability signal,
RAG/internal disagreement, environment state, gold label, attacker identity, or poison provenance.

All 300 clean and 1,260 attacked endpoints completed. One Qwen request timed out once and completed
on the resumable rerun. The final manifest has 1,260 attacked successes and zero failures.

## Pooled results

| Scope | Rows | Top-5 RAG | Top-10 RAG | Model-only | Answerability fallback | Proposed |
|---|---:|---:|---:|---:|---:|---:|
| Clean | 300 | 84.00 | **85.33** | 68.67 | 82.00 | 83.67 |
| Attacked | 1,260 | 48.97 | 53.33 | 73.02 | 80.16 | **80.48** |

On attacked rows, top-10 has 105 exclusive correct cases versus 50 for top-5, a net gain of 55
cases or 4.37 percentage points (exact paired p = 1.18e-5). On clean rows the change is 12 gains
versus eight losses, a net four cases (p = 0.503). Thus more retrieved material genuinely helps
ordinary RAG, but the attacked gain is far smaller than the 27.14-point gap between top-10 RAG and
the proposed method.

Even an oracle that chooses top-5 when it is correct and top-10 otherwise reaches only 57.30% on
attacked rows. The two retrieval budgets therefore lack enough complementary correct predictions to
approach model-only or the proposed system.

## By nominal poisoning rate

| Rate | Top-5 RAG | Top-10 RAG | Model-only | Answerability fallback | Proposed | Top-10 minus top-5 |
|---:|---:|---:|---:|---:|---:|---:|
| 0.1% | 80.16 | 80.95 | 73.02 | 86.90 | **88.10** | +0.79 |
| 0.5% | 71.43 | 71.83 | 73.02 | 83.73 | **84.52** | +0.40 |
| 1% | 50.00 | 58.33 | 73.02 | **80.56** | 80.16 | +8.33 |
| 4% | 25.00 | 32.54 | 73.02 | **75.00** | **75.00** | +7.54 |
| 8% | 18.25 | 23.02 | 73.02 | **74.60** | **74.60** | +4.76 |

The top-10 gain is negligible in the low-rate blend regime and largest at 1%--4%, where it remains
far below the internal endpoints. This directly argues against explaining the proposed low-rate
gain as merely twice the ordinary retrieval budget.

## By victim, pooled across attacked rates

| Victim | Rows | Top-5 RAG | Top-10 RAG | Model-only | Answerability fallback | Proposed |
|---|---:|---:|---:|---:|---:|---:|
| GLM | 445 | 39.78 | 44.94 | 77.53 | 80.90 | **81.12** |
| Llama | 430 | 67.67 | 71.63 | 63.95 | **81.16** | 80.93 |
| Qwen | 385 | 38.70 | 42.60 | 77.92 | 78.18 | **79.22** |

Top-10 improves top-5 for all three victims. It exceeds raw model-only for Llama, but not the
answerability-aware internal fallback, and remains far below internal knowledge for GLM and Qwen.

## Retrieval exposure

Across attacked rows, top-5 retrieves 15,518 poison documents among 26,868 total (57.76%). Top-10
retrieves more poison documents in absolute terms—19,730—but many more documents overall, producing
a lower 46.25% poison fraction. The rate-specific top-10 poison fractions are 3.08%, 10.06%,
23.67%, 73.70%, and 88.88% from 0.1% through 8%.

The dilution explains why top-10 can improve ordinary RAG even while increasing absolute poison
exposure. It does not make retrieval safe: at 8%, almost nine of every ten retrieved documents are
poison and accuracy is 23.02%.

## Interpretation for the paper

The required conclusion is nuanced:

1. Extra retrieval budget is a legitimate stronger RAG baseline and should replace top-5 as the
   strongest raw-RAG comparator where appropriate.
2. Extra material explains only a small portion of the defense's performance.
3. The current counter view is not an independent retriever; it is lower-ranked material from the
   same attacked index, processed separately after excluding the first view.
4. A remaining exact-union ablation should compare one joint interpretation of the same top-10
   documents with two separate top-5 interpretations. That would isolate evidence partitioning
   from internal knowledge.
5. The strongest present evidence for internal knowledge is that top-10 RAG and even the top-5/
   top-10 retrieval oracle remain far below the answerability fallback and proposed method.

## Artifacts

- Frozen protocol: `docs/RAG_TOP10_BASELINE_PROTOCOL.md`
- Configuration: `configs/rag_top10_confirmation_diagnostic_v1.json`
- Complete endpoints and private traces:
  `artifacts/runs/rag_top10_confirmation_v1/stage1/confirmation/rag/rag_top10_confirmation_v1/`
- Isolated request cache: `artifacts/cache/llm_rag_top10_confirmation_v1/`
- Frozen attack scope: `artifacts/evaluation/rag_top10_confirmation_v1/frozen_top5_attack_scope.json`
- Paired machine-readable evaluation:
  `artifacts/evaluation/rag_top10_confirmation_v1/paired_results.json`
- Audit: `artifacts/evaluation/rag_top10_confirmation_v1/audit.json`
