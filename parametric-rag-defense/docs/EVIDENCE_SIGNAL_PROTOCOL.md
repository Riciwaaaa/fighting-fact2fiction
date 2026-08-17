# Evidence-signal experiment

Status: collection and pre-label audit complete. This is development work on the existing 100
claims, not independent validation. Results are in `docs/EVIDENCE_SIGNAL_RESULTS.md`.

## Question

The earlier endpoint selectors often failed because they saw a compressed RAG rationale after
retrieved passages had already been blended together. This experiment tests the missing premise:
whether the uncompressed, origin-hidden passages contain an observable signal that distinguishes
cases where RAG is right from cases where the same model's closed-book endpoint is right.

It does not yet run a final arbiter. A negative signal result should stop us from spending calls on
another endpoint selector with the same information bottleneck.

## Scope

- Conditions: clean, 0.1%, 0.25%, and 0.5% Fact2Fiction.
- Models: GLM, Llama, and Qwen, with the same model used for both source endpoints and new calls.
- Activation: all cached RAG/closed-book prediction disagreements.
- Rows: 363 total—100 clean and 263 attacked.
- Unique model/claim cases: 159.
- Maximum logical calls: 159 claim plans plus 363 passage maps, before cache reuse.

The attacked activation count is larger than the 243 oracle-complementarity count reported in the
rate scan. That earlier count includes only disagreements where one endpoint is correct. The real
workflow cannot know correctness, so it also retains 20 attacked rows where the endpoints differ
but both are wrong.

## Information boundary

The claim planner sees only the original claim and date. The passage mapper sees that neutral plan,
the ten retrieval questions, and every exact-unique cached top-k excerpt. Exact duplicates are
collapsed to one alias, and passage order is deterministically shuffled using the RAG task key.

The passage mapper does not see endpoint verdicts, endpoint rationales, confidence, adopted
answers, selected ranks, model identity, poisoning rate, origin indicators, URLs, or gold. Private
poison annotations are used only after collection to explain mechanisms.

Each output must assess every passage. The initial pilot required content clusters to partition
every passage, but this proved stricter than the semantic need: models often left already-assessed
context or irrelevant passages outside the cluster list. Amendment 1 permits that omission while
still forbidding duplicate or unknown cluster membership. Clusters represent substantive repeated
assertions, not verified source independence.

The 24-row contract pilot produced 17 fully valid outputs. Six of seven failures assessed every
passage and failed only the over-strict cluster partition; one long Llama row assessed 5 of 34
passages. Before gold evaluation, Amendment 1 relaxed only cluster coverage and made subsequent
format retries name every missing passage ID. No semantic output, endpoint correctness, or label
informed the change. Every original attempt remains cached.

## Commands

Verify the frozen workload without calls:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_evidence_signal.py --prepare-only
```

Run or resume collection:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_evidence_signal.py --workers 6
```

Generated calls, raw responses, packets, manifests, failures, and token receipts are immutable and
content-addressed. Claim-only plans use the exact earlier neutral-plan request and therefore reuse
compatible cached responses.

## Decision rule

The main diagnostic set contains rows where exactly one endpoint is correct. Features derived from
the passage map are evaluated with claim-grouped cross-validation and compared with always choosing
the stronger endpoint. Condition, model identity, and private poison annotations are excluded from
the predictive feature set.

The attacked signal did not pass this gate: a decisive passage direction usually reinforced the
poisoned RAG answer, and grouped predictive gains were weak with intervals spanning zero. We do not
run a final arbiter on the same information. The revised next experiment adds symmetric,
leave-document-out counter-retrieval before arbitration; see `docs/COUNTER_RETRIEVAL_PLAN.md`.

The complete machine-readable freeze is `configs/evidence_signal_v1_freeze.json`; the contract-only
pilot correction is `configs/evidence_signal_v1_amendment_1.json`.
