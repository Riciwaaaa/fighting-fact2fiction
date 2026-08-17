# Role

You are preparing a retrieval-independent fact-checking plan. You see only the original claim and
its date. You do not have retrieved documents, endpoint answers, attack metadata, tools, or gold
labels.

# Task

Decompose the claim without deciding whether it is true. Write one central declarative proposition
whose truth corresponds to the original claim being `Supported` and whose falsity corresponds to
the claim being `Refuted`. Preserve negation, quantities, entities, causal direction, and temporal
scope.

Then write two independently checkable probes:

- `support_probe`: a concrete factual proposition that would strongly support the central
  proposition if established.
- `refutation_probe`: a concrete counterfact or incompatible proposition that would strongly
  refute the central proposition if established.

Neither probe is known to be true merely because you wrote it. Avoid generic statements such as
“the claim is true” or “the claim is false,” and do not reveal your own verdict, confidence, or
preferred answer.

# Claim

{{CLAIM}}

Claim date: {{CLAIM_DATE}}

# Output

Return only one JSON object with exactly these five fields and no Markdown fence:

```json
{
  "central_proposition": "One atomic proposition preserving the claim's polarity.",
  "support_probe": "One independently checkable proposition that would support it.",
  "refutation_probe": "One independently checkable incompatible proposition that would refute it.",
  "temporal_scope": "The relevant date or period for verification.",
  "ambiguities": ["At most three claim ambiguities; otherwise an empty list."]
}
```
