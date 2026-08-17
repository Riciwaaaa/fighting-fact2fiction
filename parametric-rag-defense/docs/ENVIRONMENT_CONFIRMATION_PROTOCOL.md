# Fresh confirmation protocol

Status: frozen on 2026-08-12 before any model call on the confirmation claims.

The purpose of this run is to test, rather than further tune, the method selected in
`configs/environment_conditioned_candidate_v1.json`. The machine-readable commitment is
`configs/environment_confirmation_protocol_v1.json`.

## Data and roles

The confirmation set contains 100 previously unused AVeriTeC training claims: 50 Supported and 50
Refuted. It has no duplicate prompts and no exact claim/date prompt overlap with the entire
AVeriTeC dev set. This is a project-level holdout; because AVeriTeC is public, it cannot prove that
a hosted model did not see the claims during pretraining.

The primary matrix is same-model: GLM 5.2, Llama 3.1 70B, or Qwen 3.5 35B-A3B performs every LLM
role in its own cell. We collect clean RAG first and then apply Fact2Fiction's second filter per
victim. Eligible claims are attacked at 0.1%, 0.5%, 1%, 4%, and 8% using nested poison prefixes.
Every intermediate response is cached in a confirmation-only namespace.

## Frozen method

Three closed-book calls provide a majority answer. If that answer is binary, it is the internal
anchor; otherwise RAG is the fallback. When RAG and the anchor disagree, the workflow makes a
second retrieval from the same potentially poisoned corpus after excluding the original document
IDs and exact texts. It does not use poison labels or a clean retriever.

Across a model-specific environment, the method counts how often answerable internal majorities
disagree with RAG and compares the count with the already frozen clean development reference.
Normal environments permit loose corroboration, suspicious environments require direct unopposed
corroboration, and critically abnormal environments disable retrieval-based overrides. The
method never receives the nominal rate, attacker identity, poison exposure, or gold.

## Decision rule for the study

The main result pools all eligible same-model attacked rows across the five rates. It passes only
if the frozen method is strictly more accurate than both raw poisoned RAG and raw closed-book
answering, at least one individual victim also has this strict pooled win, and clean accuracy is
within two percentage points of the stronger raw clean endpoint. These are workshop-scale
transfer criteria, not a claim of universal dominance; every model/rate cell will be reported.

Batch-end routing is primary. A prequential secondary evaluation exposes the cost of detection
delay: claims are deterministically ordered, each prediction uses only earlier conflict
observations, and the method stays in normal mode until 40 answerable observations exist.

After the diagonal matrix, a secondary 1% experiment uses fixed GLM and Llama attackers against
all three victims on their jointly clean-correct claims. The defense remains attacker-blind.
