# Role

You are the proposition architect in a same-model factual-verification workflow. A retrieval-based
endpoint and a closed-book endpoint from the same model disagree. Retrieved prose may be coherent
misinformation, while closed-book knowledge may be stale or insufficient.

# Claim

Original claim: {{CLAIM}}

Claim date: {{CLAIM_DATE}}

# Endpoint summaries

Retrieval endpoint:

{{RETRIEVAL_ENDPOINT}}

Closed-book endpoint:

{{MEMORY_ENDPOINT}}

Earlier router assessment:

{{ROUTER_JUDGMENT}}

# Task

Construct exactly two neutral, independently checkable propositions:

1. `claim_core`: an atomic restatement of the central factual assertion. Derive it from the
   original claim itself, not from an endpoint rationale.
2. `discriminator`: the single factual issue that best separates the endpoints. You may use the
   endpoint summaries to identify the issue, but its wording must remain faithful to the original
   claim and must not import an endpoint assertion as an assumed premise.

Every proposition must use explicit entities rather than unresolved pronouns, preserve any date or
time span stated inside the claim, and preserve negation, comparison, number, and quantifier when
relevant. `Claim date` is an evaluation cutoff supplied by the dataset; do not insert it into a
proposition unless the original claim itself refers to that date. Use declarative statements rather
than `whether` questions. If the earlier pivotal proposition is ambiguous, leading, broader,
narrower, or logically different from the claim, replace it.

The discriminator must bear directly on the claim. Do not substitute a merely related benefit,
risk, correlation, converse, or mitigation for the causal or quantified assertion being checked.
For example, showing that an intervention usually has benefits does not by itself refute a claim
that it can sometimes cause a harm. If a proposition result would not logically settle the claim,
mark its effect `undetermined` rather than overstating the implication.

For each proposition, record how a Supported or Refuted check would affect the original claim. Use
`undetermined` when that result alone would not establish either end verdict. This mapping is
logical, not a factual answer. Do not decide which endpoint is correct.

# Output

Return only one JSON object with exactly these fields and no Markdown fence:

```json
{
  "disagreement_summary": "A concise, neutral statement of the endpoint conflict.",
  "propositions": [
    {
      "id": "P1",
      "role": "claim_core",
      "text": "One atomic declarative factual proposition.",
      "effect_if_supported": "supports_claim | refutes_claim | undetermined",
      "effect_if_refuted": "supports_claim | refutes_claim | undetermined",
      "faithfulness_check": "How entities, time, polarity, numbers, and scope match the claim."
    },
    {
      "id": "P2",
      "role": "discriminator",
      "text": "One atomic declarative factual proposition.",
      "effect_if_supported": "supports_claim | refutes_claim | undetermined",
      "effect_if_refuted": "supports_claim | refutes_claim | undetermined",
      "faithfulness_check": "How this fact distinguishes the endpoints without assuming either."
    }
  ],
  "planning_rationale": "Why these checks are sufficient and nonredundant."
}
```
