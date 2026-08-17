# Precommitted internal knowledge and RAG stress-test protocol

Status: frozen before stress-view model calls on 2026-08-11.

## Research question

When same-model closed-book and RAG disagree, can a model's internal knowledge be combined with a
causal stability test over the existing retrieved context to select the better final verdict?

The intended deployment principle is condition-blind. Experiments may characterize when
model-only becomes preferable as poisoning increases, but the defense never observes the nominal
attack rate, attacker identity, document provenance, or gold label.

## Internal precommitment

No new internal answer is generated after reading retrieval. The internal record reuses the three
`internal_claim_v2` calls that were collected independently of retrieval. It contains each call's
verdict, confidence, knowledge basis, decisive propositions, premise concerns, and concise
rationale.

The claim-only `neutral_claim_plan_v1` supplies a central proposition plus concrete support and
refutation probes. These probes are not assumed true. They state, behind the same information
firewall, what evidence would support or overturn the central proposition. Although the cached plan
was collected later in wall-clock time, it saw only the claim and date; “precommitment” therefore
means pre-retrieval in information, not a claim about collection chronology.

## Fixed-retrieval stress views

The source is all 363 clean, 0.1%, 0.25%, and 0.5% rows where the same model's RAG and three-call
closed-book endpoints disagree. Existing endpoint-hidden evidence maps group passages that repeat
the same factual assertion. Passages the mapper omitted from content clustering become singleton
units, so every retrieved document remains represented.

The evidence mapper saw only the 300-character masked excerpts retained in the normalized RAG
endpoint. If multiple private documents have the same visible excerpt, they remain one inseparable
unit: the method must not distinguish identities its mapper could not distinguish.

Each row has two deterministic complementary views:

- `half_a` and `half_b` greedily balance whole assertion units by document count;
- the halves are disjoint and exhaustive over the original fixed retrieval;
- ties use cluster IDs, not condition, provenance, labels, or model performance.

When possible, a third view removes the largest direct assertion cluster aligned with the original
RAG verdict. Ties again use cluster IDs. This is a high-leverage stress test, not a poison detector.

Every view reuses the original ten questions and the unchanged `rag_answers_v1` and
`rag_verdict_v1` prompts, decoding, and victim model. There is no retrieval and no backfill.

## Exact scope and cost ceiling

Preflight over all source artifacts produced:

- 363 `half_a` views;
- 363 `half_b` views;
- 281 dominant-aligned-cluster-removal views;
- 1,007 named views total;
- 925 unique victim-visible contexts after exact-prompt deduplication;
- at most 925 answer calls and 925 verdict calls before format repairs;
- zero internal calls, retrieval calls, or backfill calls.

Identical visible prompts share one content-addressed output even if their private document
identities or condition labels differ. Each named view remains in the private manifest.

## Arbiter information boundary

The same victim model will arbitrate only on endpoint disagreements. It may see:

- claim and date;
- the RAG and closed-book endpoint labels;
- the three sealed internal assessments;
- the claim-only central proposition and support/refutation probes;
- anonymous assertion-unit sizes, stance, and directness labels;
- which anonymous units each view retains;
- original and view verdicts, confidence, and answer coverage.

It may not see raw retrieved passages, model-written factual summaries of those passages, source
identity, URLs, poison provenance, condition or rate, attacker identity, or gold. This prevents the
arbiter from simply being persuaded by the same poisoned prose again.

## Required controls

Report poisoned RAG, same-model three-call closed book, the answerability fallback, and the selected
leave-original-out corroboration method. Add:

1. a deterministic stability-only policy with no LLM arbiter;
2. a matched same-model arbiter that receives the sealed internal record and original endpoint
   metadata but not stress-view outcomes;
3. the complete arbiter with stress-view outcomes.

The matched control tests whether an extra deliberation call, rather than causal stability, creates
any improvement.

## Development interpretation

This remains method development on previously opened claims. A candidate may proceed only if it
does not reduce pooled clean accuracy relative to the selected corroboration method, beats both raw
endpoints at each attacked rate, and has positive paired net gain over the selected method for at
least two victims. All activations, gains, regressions, calls, and claim-clustered uncertainty must
be reported. Passing development does not constitute confirmation.
