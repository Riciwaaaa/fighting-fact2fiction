# Counter-retrieval workflow plan

Status: executed with one documented simplification. Results are in
`docs/COUNTER_RETRIEVAL_RESULTS.md`.

The executed first pass reused the ten cached claim-generated RAG queries rather than spending new
calls on paired query generation, and excluded every original document and exact text rather than
only model-identified decisive clusters. This stricter, deterministic exclusion was frozen before
passage-map calls. The planned LLM arbiter was also run as a frozen ablation; it was worse than the
typed corroboration rule and is not part of the selected primary method.

## Motivation

The passage-level diagnostic showed that the model can classify what retrieved text asserts, but a
coherent fabricated passage is usually treated as valid direct evidence. A useful next workflow
therefore needs an independent observation: does the decisive assertion survive retrieval from a
different query view after the original decisive material is removed?

The method remains an LLM workflow. Retrieval-stability and corroboration measurements are inputs
to the arbiter, not a fixed decision tree that silently chooses an endpoint.

## Experiment 2A — Symmetric counter-retrieval signal

For every same-model endpoint disagreement in clean, 0.1%, 0.25%, and 0.5%:

1. Reuse the cached claim-only decomposition and passage map.
2. Generate a paired, claim-only query plan: half of the queries seek observations that would
   support the claim, and half seek observations that would refute it. The prompt must not see the
   endpoints, original passages, condition, model name, origin, or gold.
3. Retrieve from the exact condition-specific corpus under two views:
   - an ordinary symmetric-query view;
   - a leave-decisive-document-out view that excludes every document underlying a direct cluster
     in the original passage report. Exclusion uses anonymous document identity, never poison
     provenance.
4. Deduplicate exact and near-duplicate assertions. Preserve anonymous document identity and
   cross-query recurrence so the report can distinguish repetition from corroboration.
5. Ask the same model for a structured corroboration report: support/refutation direction,
   independent-document count, entity/time match, numerical consistency, and whether the original
   direction survives removal.

The primary diagnostic is endpoint-selection accuracy on exclusive disagreements, grouped by claim.
Private poison counts remain explanatory metadata only. A useful signal must improve over the
stronger constant endpoint and over the current passage-map features with a claim-grouped interval
that is materially narrower than the present result.

## Experiment 2B — Same-model LLM arbiter

Only if 2A supplies useful attacked signal, run a same-model arbiter with three actions:

- `trust_rag`;
- `trust_memory`;
- `escalate`.

The arbiter receives the two endpoint verdicts, neutral claim decomposition, original structured
passage report, and counter-retrieval corroboration report. It does not see origin, nominal rate,
model identity, raw URLs, poison counts, or gold. It must state the pivotal factual conflict and
explain whether independent evidence resolves it. The evaluated binary verdict is still copied
from an existing endpoint; escalation is handled by the predeclared policy below.

Primary escalation policy: ask the same model one retrieval-isolated, premise-aware question about
the pivotal assertion, then let a final same-model selector choose an existing endpoint. This keeps
the same-model pipeline as the primary result.

Secondary plus variant: route only escalated cases to one fixed different-family model. Report its
incremental accuracy and cost separately and compare it with the three-model closed-book panel, not
only with same-model memory.

## Controls and ablations

- poisoned RAG and same-model closed book;
- stronger endpoint chosen globally per model, without claim-level routing;
- current original-passage report without counter-retrieval;
- counter-retrieval structure with a simple grouped logistic selector;
- equal-call direct claim answering;
- arbiter with the corroboration report shuffled across claims;
- ordinary symmetric retrieval versus leave-document-out retrieval;
- same-model escalation versus the fixed cross-model plus variant.

## Development and evaluation policy

The present 100 claims may be tuned freely. All rates for the same claim must stay in one fold. Do
not use nominal rate or model identity as row-level selector inputs. Rate-specific operating modes
may be reported only as deployment priors fixed before evaluating a claim, never as hidden access
to whether that individual row was attacked.

Before any new confirmation claim is opened, freeze prompts, model roles, corpus construction,
document-exclusion semantics, decoding, escalation budget, controls, and success gates. The primary
paper table must be per victim with the same model performing RAG, closed book, evidence reports,
and arbitration.

Suggested development gate:

- at 0.1% and 0.25%, beat both same-model endpoints for at least one victim and in the pooled
  eligible set;
- preserve clean RAG within one claim per victim;
- at 0.5%, match the stronger endpoint or correctly escalate rather than forcing a blend;
- show benefit over the equal-call direct-answer control;
- verify the selected design under a fixed strong attacker before fresh-claim confirmation.

If 2A fails, stop method construction and write the workshop paper as a rate-dependent negative
characterization: internal knowledge is useful as a fallback, but passage semantics alone cannot
authenticate poisoned evidence.
