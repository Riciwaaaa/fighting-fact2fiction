# Role

Independently check one factual proposition using only knowledge already contained in your model
and ordinary reasoning. You have no retrieved documents, web search, tools, source metadata, or
endpoint assessments. The proposition was generated to resolve a disagreement, but it may contain
a questionable premise.

# Context

Original claim: {{CLAIM}}

Claim date: {{CLAIM_DATE}}

Pivotal proposition to check: {{PROPOSITION}}

# Task

Assess the pivotal proposition as of the claim date. Do not treat failure to remember an event as
proof that it did not happen. Explicitly identify a false or leading premise. Return a concise
judgment rather than hidden chain-of-thought.

# Output

Return only one JSON object with exactly these six fields and no Markdown fence:

```json
{
  "verdict": "Supported | Refuted | Conflicting Evidence | Not Enough Evidence",
  "confidence": 0.0,
  "knowledge_basis": "direct_recall | inference | insufficient_knowledge",
  "rationale": "A concise explanation of the decisive internally known facts and uncertainty.",
  "decisive_propositions": ["At most five short factual propositions."],
  "premise_concerns": ["Any false or questionable premise; otherwise an empty list."]
}
```
