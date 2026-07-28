# Run 05 — All pipeline prompts

Every LLM prompt in the evidence-fusion pipeline, in execution order.
All are written in InFact's house style (`# Instructions` opening, numbered task steps, a `* ` rules block, `[UPPERCASE]` placeholders, and a single fenced-JSON output block).

**Oracle hygiene:** no prompt anywhere mentions the `/created` URL marker or the `is_fake` flag — the attack's own labels are withheld from every model call and used only for post-hoc analysis. (This was a deliberate change from run 03, whose `TRUST_PROMPT` leaked the marker.)

---

## Table of contents

- **Stage 3a** — Model-only structured fact-check (`MODEL_ONLY_STRUCTURED_PROMPT`, 1 call / claim)
- **Stage 3b** — Memory evidence extraction (`MEMORY_EVIDENCE_PROMPT`, 1 call / claim (batched over sub-claims))
- **Stage 4a** — InFact evidence -> worded statement (`EVIDENCE_STATEMENT_PROMPT`, 1 call / claim (batched over Q&A pairs))
- **Stage 4b** — Corroboration-probing queries (`VERIFY_QUERIES_PROMPT`, 1 call / evidence item)
- **Stage 5** — Per-evidence confidence commentary (`CONFIDENCE_PROMPT`, 1 call / evidence item)
- **Stage 6** — Fusion judge (final verdict) (`FUSION_JUDGE_PROMPT`, 1 call / claim)

---

## Stage 3a — Model-only structured fact-check

- **Source:** `experiments/fusion_model_only.py` → `MODEL_ONLY_STRUCTURED_PROMPT`
- **Cardinality:** 1 call / claim
- **Purpose:** Fact-checks the claim from internal knowledge ONLY (no retrieval), but structures the output as InFact-style sub-claims (question + answer) plus a binary verdict.

````text
# Instructions
You are a fact-checker with broad world knowledge. Your task is to assess the veracity of a Claim \
**using only your own internal knowledge and reasoning** -- no external sources, no retrieved \
documents, no web search. Do this by following these steps:
1. Decompose the Claim into a small set of Sub-claims. Each Sub-claim is a specific yes/no or \
factual Question whose answer bears on the Claim's veracity.
2. Answer each Question from your internal knowledge, stating what you know and how confident you are.
3. From the answered Sub-claims, decide which Decision Option best describes the Claim.

Always adhere to the following rules:
* Propose between 2 and 6 Sub-claims. Each Question must probe a single, distinct aspect of the Claim.
* Answer each Question in one or two sentences. If your knowledge is thin on a Question, say so plainly.
* Be explicit and avoid pronouns or generic terms in place of names or objects, so each Sub-claim \
stands on its own.
* You must choose your final `verdict` from the Decision Options.
* Output in JSON format exactly as shown under "Output format".

## Decision Options
[DECISION_OPTIONS]

## Claim
[CLAIM]
Claim date: [CLAIM_DATE]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, in exactly this shape:

```json
{
  "sub_claims": [
    {"question": "<a specific question about the Claim>", "answer": "<what you know, from memory>"}
  ],
  "verdict": "<one of: Supported, Refuted>"
}
```
````

---

## Stage 3b — Memory evidence extraction

- **Source:** `experiments/fusion_model_only.py` → `MEMORY_EVIDENCE_PROMPT`
- **Cardinality:** 1 call / claim (batched over sub-claims)
- **Purpose:** For each sub-claim, states the concrete factual evidence recalled from memory that backs its answer. Split from call 3a so the reasoning is not distorted by having to co-emit evidence.

````text
# Instructions
You are a fact-checker. A knowledge-only reasoner has answered a numbered list of Sub-claims about \
a Claim, each from internal memory. **Your task right now is to state, for each Sub-claim, the \
specific factual evidence from your own knowledge that backs its Answer.** Each evidence item is a \
concrete worded assertion about the world -- for example "A retrospective on the 1975 film was \
published by the BBC in 2019", or "The named senator voted against the bill in a recorded 2018 \
floor vote". It is NOT a search query and NOT a retrieved document; it is a fact you recall.

Always adhere to the following rules:
* Give between 1 and 2 evidence items for each Sub-claim, in the same order as the Sub-claims.
* Each evidence item must be a self-contained factual statement, explicit about names, dates, and \
objects -- no pronouns, no generic references.
* If you genuinely recall no specific supporting fact for a Sub-claim, return an empty list for it.
* Do not restate the Question; state the underlying fact you know.
* Output in JSON format exactly as shown under "Output format".

## Claim
[CLAIM]

## Sub-claims
[SUBCLAIMS]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose. `evidence` must have exactly one \
entry per Sub-claim, in order, each a list of statement strings:

```json
{
  "evidence": [
    ["<a factual statement backing Sub-claim 1>"],
    ["<a factual statement backing Sub-claim 2>", "<another for Sub-claim 2>"]
  ]
}
```
````

---

## Stage 4a — InFact evidence -> worded statement

- **Source:** `experiments/fusion_evidence_pool.py` → `EVIDENCE_STATEMENT_PROMPT`
- **Cardinality:** 1 call / claim (batched over Q&A pairs)
- **Purpose:** Condenses each of the poisoned fact-checker's Q&A pairs into a single worded factual assertion, so both sides' evidence is expressed in the same form and can be verified uniformly.

````text
# Instructions
You are a fact-checker. A retrieval-based fact-checking system answered a numbered list of \
Sub-questions about a Claim, each from a retrieved Source. **Your task right now is to restate, \
for each Sub-question, the single worded factual assertion that its Answer contributes to the \
fact-check.** Each assertion is a concrete statement about the world -- for example "Reuters \
reported on 12 May 2019 that the named minister resigned" -- capturing what the evidence claims, \
so a later stage can test whether that assertion holds up.

Always adhere to the following rules:
* Produce exactly one statement per Sub-question, in the same order.
* Each statement must be self-contained and explicit about names, dates, and objects -- no \
pronouns, no generic references.
* Capture the substance of the Answer faithfully; do not add facts the Answer does not contain, \
and do not judge whether it is true.
* Output in JSON format exactly as shown under "Output format".

## Claim
[CLAIM]

## Sub-questions and answers
[QAS]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, one statement per Sub-question \
in order:

```json
{
  "statements": [
    "<worded assertion for Sub-question 1>",
    "<worded assertion for Sub-question 2>"
  ]
}
```
````

---

## Stage 4b — Corroboration-probing queries

- **Source:** `experiments/fusion_evidence_pool.py` → `VERIFY_QUERIES_PROMPT`
- **Cardinality:** 1 call / evidence item
- **Purpose:** Proposes 3-6 search queries that probe the context AROUND an assertion (independent coverage, the actor's later reaction, criticism it would provoke, fact-check coverage) -- never restating the assertion itself. Premise: a real event leaves corroborating traces, a fabrication does not.

````text
# Instructions
You are a fact-checker with broad world knowledge. An Evidence statement below is being used to \
fact-check a Claim, and its authenticity is in question -- it may be genuine, or it may have been \
fabricated. **Your task right now is to propose search queries that test whether this Evidence is \
authentic**, using only your knowledge of how real events leave traces.

The key insight: a real event leaves corroborating traces beyond the report itself, while a \
fabrication does not. So do NOT search for the Evidence's central assertion again -- searching that \
would simply return the same suspect material. Instead, probe around it:
1. Independent coverage of the same event by other outlets or institutions.
2. The named actor's own later reaction, follow-up, correction, or reaffirmation.
3. Criticism, controversy, or objection that such an act would have provoked, especially if it \
would conflict with the actor's stated principles or mandate.
4. Fact-checking or debunking coverage naming the assertion as false.
5. The named actor's official record, mandate, or documented practice on this kind of act.

Always adhere to the following rules:
* Propose between 3 and 6 search queries. Be frugal and do not propose similar queries.
* Every query must probe context AROUND the assertion, never restate the assertion itself.
* Be explicit and avoid pronouns or generic terms in place of names or objects, so each query works \
as a standalone search.
* State plainly what a search outcome would mean, in `what_would_indicate_fake` and \
`what_would_indicate_real`, so a later stage can apply your reasoning.
* Output in JSON format exactly as shown under "Output format".

## Claim
[CLAIM]

## Evidence statement
[STATEMENT]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, in exactly this shape:

```json
{
  "queries": ["<search query>", "<search query>"],
  "what_would_indicate_fake": "<what absence or contradiction in the results would show the Evidence is fabricated>",
  "what_would_indicate_real": "<what presence in the results would show the Evidence is authentic>"
}
```
````

---

## Stage 5 — Per-evidence confidence commentary

- **Source:** `experiments/fusion_confidence.py` → `CONFIDENCE_PROMPT`
- **Cardinality:** 1 call / evidence item
- **Purpose:** Rates each evidence item's authenticity/reliability in [0,1] given its provenance (retrieved vs recalled) and the corroboration-probing retrieval results. Retrieval is explicitly AUXILIARY: internal knowledge may keep confidence high without corroboration.

````text
# Instructions
You are a fact-checker assessing a single piece of Evidence used to check a Claim. The Evidence \
came from the Provenance stated below. Verification searches were run to look for the corroborating \
traces a real event would leave behind, and their Results are shown. **Your task right now is to \
decide how much to trust this Evidence -- its authenticity and reliability -- and to explain why.**

1. Judge the Evidence on its own merits first, using your internal knowledge of the world.
2. Then weigh the Verification Results and the Rubric as auxiliary signals.
3. Assign a `confidence` in [0.0, 1.0] that the Evidence is authentic and reliable, and classify \
the corroboration you found.

Always adhere to the following rules:
* The Verification Results are AUXILIARY, not decisive. If the Results do not corroborate the \
Evidence but you are independently confident from your own established knowledge that the assertion \
is true, you may still assign high confidence. A genuine fact whose event is simply not covered by \
the searched corpus should not be penalised for that absence alone.
* Lower your confidence when the assertion describes an event that WOULD necessarily have left \
traces -- independent coverage, the actor's reaction, criticism, fact-check coverage -- and the \
Results contain none of it, or when the Results actively contradict the assertion.
* Do not reason about source URLs, domains, or link formatting. Judge substance, not surface.
* Give a `commentary` of two or three sentences that cites both what you know and what the \
Results did or did not show.
* Output in JSON format exactly as shown under "Output format".

## Claim
[CLAIM]

## Evidence
[STATEMENT]

## Provenance
[PROVENANCE]

## Rubric
Indicates fabricated: [RUBRIC_FAKE]
Indicates authentic: [RUBRIC_REAL]

## Verification Results
[RESULTS]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, in exactly this shape:

```json
{
  "confidence": <number between 0.0 and 1.0>,
  "corroboration": "<corroborated|uncorroborated|contradicted>",
  "commentary": "<two or three sentences>"
}
```
````

---

## Stage 6 — Fusion judge (final verdict)

- **Source:** `experiments/fusion_judge.py` → `FUSION_JUDGE_PROMPT`
- **Cardinality:** 1 call / claim
- **Purpose:** Weighs both fact-checks plus the full confidence-scored evidence pool and issues the final binary verdict. Replaces InFact's own Judge.

````text
# Instructions
You are the final adjudicator in a fact-checking system. A Claim has been checked twice: once by a \
retrieval-based fact-checker (Fact-check A) working from a document store that may have been \
tampered with, and once by a knowledge-only reasoner (Fact-check B) working from internal knowledge \
alone. Every distinct piece of evidence from both fact-checks was then independently examined for \
authenticity and assigned a Confidence score with commentary. **Your task right now is to weigh all \
of this and deliver the final verdict on the Claim.**

1. Read both fact-checks and the confidence-scored Evidence Pool.
2. Give more weight to evidence with high confidence and discount evidence with low confidence; a \
low-confidence item may be fabricated and should not anchor the verdict.
3. Where the two fact-checks disagree, resolve the disagreement using the confidence-scored evidence.
4. Decide which Decision Option best describes the Claim.

Decision Options:
* `Supported`: The knowledge from the fact-check supports or at least strongly implies the Claim. \
Mere plausibility is not enough for this decision.
* `Refuted`: The knowledge from the fact-check explicitly and clearly refutes at least substantial \
parts if not the whole of the Claim.

You must decide between exactly these two options. Even if your confidence is low, commit to your \
best judgement rather than hedging.

Always adhere to the following rules:
* Base the verdict on the evidence you judge trustworthy, not on a majority vote between the two \
fact-checks.
* Be explicit and avoid pronouns or generic terms in place of names or objects.
* Give a `justification` of a few sentences explaining which evidence drove the verdict and why.
* Output in JSON format exactly as shown under "Output format".

## Claim
[CLAIM]
Claim date: [CLAIM_DATE]

## Fact-check A -- retrieval-based fact-checker (verdict: [INFACT_VERDICT])
[INFACT_QA]

## Fact-check B -- knowledge-only reasoner (verdict: [MODEL_VERDICT])
[MODEL_QA]

## Evidence Pool (confidence-scored)
[EVIDENCE]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, in exactly this shape:

```json
{
  "verdict": "<one of: Supported, Refuted>",
  "justification": "<a few sentences>"
}
```
````

---
