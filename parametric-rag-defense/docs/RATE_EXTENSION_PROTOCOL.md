# Frozen 0.1% rate extension and crossed-model diagnostic

Frozen on 2026-08-10, before producing any Stage C output for the 0.1% condition or any crossed
attacker-victim RAG output. The machine-readable specification is
`configs/stage4_rate_extension_freeze.json`.

## Question 1: does the frozen workflow generalize at lower poison exposure?

Apply the already selected endpoint-only router plus targeted Stage C workflow without modifying
its prompts, decoding, activation, or output restriction. RAG, closed-book, router, proposition
checker, and selector use the same model within each row. Run all three models on the 60-claim
method-design partition under clean and Fact2Fiction 0.1% conditions.

A model passes method-design only when its 0.1% Stage C correct count is strictly greater than
both its same-model RAG and same-model closed-book correct counts, while its clean accuracy is no
more than two percentage points below the stronger clean endpoint. Only passing models are run
once on the untouched 40-claim development-validation partition. No method changes are allowed
between design and validation.

Because one claim on the 40-claim clean validation split is 2.5 percentage points, validation
reports zero loss, a one-claim loss, and larger losses separately rather than concealing the
finite-sample resolution behind a rounded threshold.

This is a rate-curve extension. Fact2Fiction 1% remains the main attack condition; 0.1% is not a
replacement headline setting.

## Question 2: are attacker strength and victim sensitivity confounded?

At Fact2Fiction 1%, cross the three existing poison generators with all three victims on the 61
claims eligible for every victim. Reuse the exact generated poison artifacts. For each cell, keep
the clean knowledge base, injection rule, retriever, top-k, victim prompt, and victim decoding
fixed. Report all nine cells, including the three existing diagonal cells.

This matrix diagnoses transfer strength and victim sensitivity. It must not be used to choose a
convenient weak attacker and redefine the main threat model.

## Required artifacts

- Immutable router, proposition-check, selector, and crossed-RAG outputs.
- Resumable JSONL progress ledgers and private manifests.
- Per-model exact counts, macro-F1, endpoint oracle, paired comparisons, and clean deltas.
- Per attacker-victim cell: accuracy, attack success rate, poison retrieval exposure, and realized
  injection counts.
- An audit confirming frozen hashes, same-model identity for the defense, prompt privacy, complete
  matrix coverage, and no missing outputs.
