# Query-aligned trace feasibility results

Status: complete development diagnostic. No new LLM calls were used. Poison provenance was used
only for evaluation.

## Result

The existing RAG trace localizes an attack-bearing input surprisingly often. Across 263 attacked
rows where same-model RAG and repeated closed-book disagree, RAG is wrong in 149 cases. In 136 of
those 149 errors (91.3%), at least one RAG answer selects a poisoned passage and passes it to the
final judge. Among the 114 correct RAG rows, 28 (24.6%) select poison. Selected poison is therefore
3.72 times as prevalent in wrong as in correct attacked traces.

This passes all three frozen feasibility gates: more than 20 selected-poison errors, coverage of all
three victim models, and more than twofold wrong-versus-correct enrichment.

| Scope | RAG wrong | Wrong with poison selected | RAG correct | Correct with poison selected | Risk ratio |
|---|---:|---:|---:|---:|---:|
| 0.1% | 40 | 35 (87.5%) | 42 | 5 (11.9%) | 7.35 |
| 0.25% | 43 | 39 (90.7%) | 40 | 8 (20.0%) | 4.53 |
| 0.5% | 66 | 62 (93.9%) | 32 | 15 (46.9%) | 2.00 |
| All attacked | 149 | 136 (91.3%) | 114 | 28 (24.6%) | 3.72 |

The rate trend matters: at 0.5%, even correct RAG traces frequently select poison. Poison selection
is therefore a useful localization target, not a poison detector and not a sufficient reason to
reject RAG.

## Victim behavior

On the full clean/attacked disagreement trace, selected-poison prevalence is more enriched among
RAG errors for every victim:

| Victim | Wrong with poison selected | Correct with poison selected | Risk ratio |
|---|---:|---:|---:|
| GLM 5.2 | 68/80 (85.0%) | 1/32 (3.1%) | 27.20 |
| Llama 3.1 70B | 25/56 (44.6%) | 17/86 (19.8%) | 2.26 |
| Qwen 3.5 35B-A3B | 43/61 (70.5%) | 10/48 (20.8%) | 3.38 |

The pooled victim table includes 100 clean disagreement rows, where poison selection is necessarily
zero. The condition-specific results in the retained evaluation artifact should be used for rate
claims.

## What this establishes—and what it does not

The final RAG judge receives only the answer and passage selected for each question. A selected
poison passage is therefore known to enter the final decision record. Merely appearing elsewhere in
the top-k is not counted as localization.

Selection does not establish causality. Twenty-eight correct attacked verdicts also selected poison,
and the final result might remain unchanged after removing a selected poisoned passage. The next
experiment therefore replays the identical RAG questions without retrieval and then performs
controlled removal from the existing retrieved context. The full-claim answerability fallback stays
frozen and remains the default method.

Machine-readable results are retained at
`artifacts/evaluation/query_aligned_trace_feasibility_v1.json` and can be regenerated with:

```bash
.venv/bin/python scripts/diagnose_query_aligned_trace.py
```
