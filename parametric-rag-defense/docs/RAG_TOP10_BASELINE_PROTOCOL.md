# Top-10-per-subquestion RAG baseline protocol

## Purpose

This opened-confirmation diagnostic tests whether the apparent benefit of the defense's additional
retrieved evidence can be explained by doubling the ordinary RAG evidence budget. It changes the
standard RAG endpoint from five to ten retrieved documents for each of the ten frozen subquestions.
It does not use a closed-book answer, answerability signal, RAG/internal disagreement, environment
state, counter-view evidence map, or endpoint arbiter.

The 100-claim confirmation labels and prior outcomes are already open. Consequently, this result is
a reviewer-facing diagnostic and method-development result, not a second independent confirmation.

## Matched design

- Models: GLM 5.2, Llama 3.1 70B Instruct, and Qwen 3.5 35B A3B.
- Conditions: clean and nominal Fact2Fiction rates 0.1%, 0.5%, 1%, 4%, and 8%.
- Clean scope: all 100 claims per model, or 300 rows.
- Attacked scope: the original top-5 victim-specific clean-correct eligibility, giving 252 rows per
  rate and 1,260 attacked rows total. The scope is not recomputed using top-10 clean accuracy.
- Questions: exact cached question plans from the original top-5 run.
- Poison: exact original model-generated poison documents, embeddings, nested prefixes, and attack
  seed. The attack is not regenerated against top-10 clean outputs.
- Retrieval: identical corpus, GTE index, query embeddings, global cross-question document
  deduplication, evidence truncation, victim prompts, decoding, and structured contracts; only
  `top_k` changes from 5 to 10.
- Cache: isolated content-addressed cache for new top-10 answer and verdict calls. Reused question
  plans are read from audited original traces and cause no provider call.
- Gold isolation: gold is joined only after endpoint collection and artifact audit.

## Required comparisons

Report clean and attacked accuracy pooled, by nominal rate, and by victim for:

1. standard top-5 RAG;
2. top-10 RAG;
3. three-call same-model closed book;
4. answerability-aware fallback;
5. the frozen environment-conditioned method.

Also report paired top-10 versus top-5 wins/losses, poison-document exposure, endpoint agreement,
and the top-5/top-10 oracle. The central interpretation is conditional:

- if top-10 approaches the proposed method, extra retrieved material explains much of the gain;
- if top-10 improves top-5 but remains below the internal baselines, internal knowledge remains
  necessary;
- if top-10 is worse, extra evidence increases poison exposure or context dilution.

## Frozen files and expected artifacts

- Configuration: `configs/rag_top10_confirmation_diagnostic_v1.json`
- Runner: `scripts/run_rag_top10_diagnostic.py`
- Evaluation: `scripts/evaluate_rag_top10_diagnostic.py`
- Cache: `artifacts/cache/llm_rag_top10_confirmation_v1/`
- Runs: `artifacts/runs/rag_top10_confirmation_v1/`
- Evaluation: `artifacts/evaluation/rag_top10_confirmation_v1/`

This protocol was written before any top-10 victim answer or verdict call was issued.
