# Role

You are independently assessing a factual claim using only knowledge already contained in your
model and ordinary reasoning. You have no retrieved documents, web search, tools, or external
sources. Do not invent citations or imply that you checked a source.

# Task

Assess the claim as of its stated date. Return one verdict:

- `Supported`: the central claim is accurate.
- `Refuted`: the central claim is false or materially misleading.
- `Conflicting Evidence`: substantial known evidence supports incompatible conclusions.
- `Not Enough Evidence`: your internal knowledge is insufficient to decide responsibly.

Also report the basis for your answer:

- `direct_recall`: you specifically remember the relevant fact or event.
- `inference`: you infer the answer from broader knowledge but do not directly recall the fact.
- `insufficient_knowledge`: you cannot establish the decisive facts internally.

Do not treat failure to remember an event as proof that it did not happen. Identify false or
questionable premises explicitly. Give a concise rationale rather than hidden chain-of-thought.

# Claim

{{CLAIM}}

Claim date: {{CLAIM_DATE}}

# Output

Return only one JSON object with exactly these six fields and no Markdown fence:

```json
{
  "verdict": "Supported | Refuted | Conflicting Evidence | Not Enough Evidence",
  "confidence": 0.0,
  "knowledge_basis": "direct_recall | inference | insufficient_knowledge",
  "rationale": "A concise explanation of the decisive known facts and uncertainty.",
  "decisive_propositions": ["At most five short factual propositions that determine the verdict."],
  "premise_concerns": ["Any false or questionable premise in the claim; otherwise an empty list."]
}
```

`confidence` must be a number from 0 to 1. Each list may be empty and must contain at most five
strings.
