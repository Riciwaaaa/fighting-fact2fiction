# Query-aligned internal audit protocol

Status: trace-feasibility protocol frozen before aggregate analysis on 2026-08-11.

## Purpose

The selected low-rate method remains unchanged. Its default is the three-call, full-claim
answerability fallback, and its current guarded override is leave-original-out corroboration. This
experiment asks whether the RAG trace can support a more internal-knowledge-centered diagnostic
without allowing that untested diagnostic to control predictions.

The proposed diagnostic replays the RAG system's exact claim-generated questions without retrieved
text. Before paying for those calls, this protocol tests whether existing failed RAG traces contain
an evidence item that can be localized at all.

## Why selected evidence matters

The victim retrieves up to five results for each of ten questions, but it selects at most one
passage per answered question. The final judge receives only the question, generated answer, and
selected passage. Consequently:

- poison appearing anywhere in the top-k is exposure, not localization;
- poison selected as the answer's cited passage entered the final decision record;
- even selected poison is not yet causal evidence, because removing it may leave the verdict
  unchanged.

Poison provenance is private evaluation metadata. No defense prompt or decision rule may observe
it.

## Frozen artifact-only analysis

Analyze the 363 existing clean/low-rate rows where same-model RAG and the three-sample closed-book
majority disagree. Report, overall and by victim/rate:

1. RAG error counts;
2. poison exposure at row and question level;
3. selected-poison counts at row and answer level;
4. selected-poison prevalence for RAG-wrong and RAG-correct rows;
5. the risk ratio between those prevalences;
6. distinct victim/claim cases available for subsequent replay.

Proceed to model calls only if attacked RAG errors include at least 20 selected-poison rows, those
rows cover at least two victim models, and the selected-poison prevalence is at least twice as high
for wrong RAG endpoints as for correct endpoints. These are feasibility gates, not performance
claims.

## Conditional follow-up

If the gate passes:

1. Ask the same victim model each exact RAG question in a fresh closed-book context. Cache every
   request, raw response, parsed response, retry, and token receipt.
2. Compare the internal answer with the RAG answer, without exposing endpoint labels, poison
   provenance, rate, or gold.
3. On a bounded set, remove selected evidence from the already retrieved context without a second
   retrieval. Include selected-poison rows and matched rows whose selected passage is clean.
4. Re-run the standard answer and verdict stages. A passage is called influential only when its
   removal changes the downstream answer or verdict; provenance remains evaluation-only.
5. Test any guarded override against both the frozen answerability fallback and the selected
   corroboration method. Report activations, gains, and regressions per model and rate.

The diagnostic is rejected as a method component if it degrades the frozen candidate. It may still
be reported as mechanistic analysis.
