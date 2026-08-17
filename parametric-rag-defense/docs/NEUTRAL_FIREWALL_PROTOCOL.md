# Frozen neutral-planning and safety-firewall protocol

Status: frozen before producing any Stage 5 model output; development experiment; original locked
claims remain unopened

## Why this iteration exists

The completed crossed Stage C workflow improves its initial router on attacked disagreements, so
the final selector is not uniformly broken. Its strong-attacker error asymmetry is nevertheless
unacceptable. Under GLM-generated poison there are 78 cases where only model-only is correct and
11 where only RAG is correct. Stage C recovers seven of the latter but sacrifices fifteen of the
former. The next selector must therefore be much more conservative about returning to retrieval
without simply hard-coding attacker identity.

The existing pivotal proposition is also chosen after reading the RAG rationale. Even though the
subsequent check is retrieval-isolated, coherent poison can frame what gets checked. Stage 5 moves
claim decomposition before endpoint exposure and prevents the final selector from reading either
endpoint rationale.

## Primary workflow

The same victim model performs every role. Endpoint agreement is copied without a call. For an
endpoint disagreement:

1. A neutral planner sees only the original claim and date. It produces a polarity-preserving
   central proposition, one support probe, one refutation probe, temporal scope, and ambiguities.
   It is forbidden to answer the claim.
2. A supportive retrieval-isolated call and a skeptical retrieval-isolated call independently
   assess the original claim using the neutral plan as hypotheses rather than facts.
3. A firewalled selector sees the original claim/date, the two endpoint labels, the neutral plan,
   and the two internal judgments. It cannot see retrieved text, the RAG rationale, memory samples,
   endpoint confidence, coverage, attacker identity, condition, or gold.
4. The selector can copy only retrieval or memory. Memory is the fallback when the isolated bundle
   is insufficient, internally conflicting, premise-dependent, or merely inferential. Retrieval
   requires specific independent reasons that memory is wrong and convergence on retrieval's
   verdict.

This is an LLM workflow policy, not a fixed attacker-specific decision tree. The model still makes
the reliability judgment, but the information channel that previously allowed a coherent poisoned
rationale to re-enter the final decision has been removed.

## Exact-call control

The `direct_deliberation` control uses the same maximum budget of four calls per disagreement.
Three retrieval-isolated direct end-claim assessments replace the plan/support/counter sequence:
one balanced, one premise-skeptical, and one focused on temporal/entity/quantity binding. The same
firewalled selector receives their structured judgments and the two endpoint labels.

If this control matches or beats the neutral workflow, the evidence supports “additional
closed-book deliberation” rather than a specific benefit from neutral decomposition and targeted
counter-checking.

## Scope and workload

- 300 clean rows and all 549 crossed 1% attack rows.
- 357 endpoint-disagreement rows, representing 186 unique victim-model/claim pairs and 208 unique
  endpoint-label inputs.
- At most 766 new calls per variant and 1,532 total. Content-addressed outputs are reused whenever
  two attack conditions produce the same inference-visible input.
- The final manifest contains 357 row descriptors per variant so every attacker-victim cell remains
  auditable even when a model call is reused.

## Frozen evaluation

The previous two-victim practical gate is retained: for each victim, aggregate the three attacker
cells, beat both RAG and model-only, and lose at most two clean points; at least two victims must
pass. This iteration adds two requirements:

- Under the strongest GLM attacker, aggregate Stage 5 across victims and do not fall below
  model-only.
- Across all 549 attacked rows, the neutral workflow must strictly beat the exact-call direct
  control.

All cells, retrieval-only recoveries, model-only sacrifices, paired tests, and 10,000-sample
claim-clustered intervals are mandatory. The current crossed outcomes informed this design, so a
pass remains development evidence rather than a held-out confirmation.

The exact hashes, prompts, decoding, expected counts, source artifacts, and gates are in
`configs/stage5_neutral_firewall_freeze.json`.
