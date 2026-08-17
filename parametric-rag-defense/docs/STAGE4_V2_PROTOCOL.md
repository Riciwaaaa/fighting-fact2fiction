# Stage 4 v2 preregistered method-design protocol

Status: completed as a negative method-design ablation; it beats both attacked endpoints but fails
the clean gate; it was not taken to validation and the original locked test remains unopened

Pilot amendment: a one-row method-design smoke test found that the architect appended the dataset
claim date as an event-time qualifier and that the adjudicator described inference-labeled checks
as direct recall. Before the full run, the generic prompts were amended to treat claim date only as
an evaluation cutoff unless it appears in the claim, reject logically related-but-nondecisive
discriminators, and provide deterministic verdict/knowledge-basis counts to the adjudicator. No
decision or result from `development_validation` was observed.

Single permitted redesign: a second method-design smoke test exposed a more consequential failure.
Four unanimous `direct_recall` checks and their declared logical mappings supported the original
claim, but the final adjudicator re-read the poisoned endpoint rationale and selected the opposite
verdict. The full run therefore uses an information firewall: a new internal synthesizer resolves
checks without seeing endpoints, and a final selector receives only endpoint verdict/reliability
summaries plus that isolated synthesis—never endpoint rationales or retrieved prose. The equal-call
control mirrors the seven-call structure. This redesign addresses a workflow-level re-poisoning
failure and is the only post-pilot redesign allowed by this protocol.

The firewalled selector policy is frozen before the full run: self-reported confidence is not a
ranking signal; an isolated `Not Enough Evidence` result cannot negate a binary RAG verdict; and an
inference with unresolved entity/date/scope cannot overturn a stable repeated memory verdict.

## Objective

At a 1% Fact2Fiction attack rate, determine whether proposition-structured access to one model's
internal knowledge improves its own RAG endpoint while outperforming that same model's closed-book
endpoint. The primary model is Llama 3.1 70B because the frozen endpoints provide seven recoverable
cases above its stronger endpoint on the method-design partition.

## Scope and noninterference

- Tune and diagnose only on the frozen 60-claim `method_design` partition.
- Initial conditions are clean and `fact2fiction_p0.01`; activation is endpoint disagreement in
  both conditions and therefore does not expose attack status.
- Reuse all Stage 1 endpoints and Stage 3 endpoint-only router outputs exactly.
- Use the same model for RAG, closed-book, proposition planning/checking, and adjudication.
- Never expose gold labels, attack condition/rate, model identity, URLs, or clean/poison source IDs
  in an inference message.
- Keep the 40-claim `development_validation` partition sealed until prompts, seeds, activation,
  action space, and success gates are frozen.

## Proposition workflow

For every endpoint disagreement:

1. A proposition architect sees the original claim/date, endpoint summaries without retrieved
   excerpts, and the frozen router record. It produces exactly one claim-grounded core proposition
   and one neutral discriminator proposition.
2. Each proposition is checked twice in fresh closed-book contexts. A checker sees only the
   original claim/date, proposition role, and proposition text—never endpoints or retrieved text.
3. A retrieval-isolated internal synthesizer sees only the claim, proposition plan, four checks,
   and deterministic proposition-to-claim effect counts. It produces an internal end verdict.
4. A firewalled final selector sees only minimal endpoint verdict/reliability metadata and the
   isolated synthesis. It never sees endpoint rationales or retrieved content and selects the RAG,
   memory, or isolated-internal candidate.
5. Agreement cases retain the common endpoint verdict without additional calls.

The workflow uses seven calls per disagreement: one architect, four factual checks, one isolated
synthesizer, and one firewalled selector. All calls and derived records are content-addressed and
cached.

## Equal-call direct control

The control also uses seven calls per disagreement: five fresh closed-book answers to the original
end claim, one retrieval-isolated synthesis, and the same firewalled selector. This is deliberately
a strong control: proposition verification must add value beyond simply spending the same
inference budget on more model-only answers.

## Frozen decoding

- Temperature: 0.2; top-p: 0.7.
- Architect seed: 101.
- Proposition check seeds: 211 and 223 for `claim_core`; 227 and 229 for `discriminator`.
- Direct-control seeds: 101, 211, 223, 227, and 229.
- Retrieval-isolated synthesis seed: 263.
- Final adjudicator seed: 307.
- At most two format-repair retries; retries change only the prompt-version cache identity.

## Method-design decision rule

The proposition workflow is eligible to freeze for validation only if, for Llama on method-design:

1. 1% accuracy is strictly above both same-model poisoned RAG and same-model closed-book;
2. clean accuracy is no more than two points below the better clean endpoint;
3. paired 1% gains over closed-book exceed regressions;
4. it is not less accurate than the equal-call direct control at 1%; and
5. qualitative audit finds no systematic proposition leakage, unfaithful polarity/scope, or
   unjustified use of `Not Enough Evidence` as negative evidence.

If v2 fails, at most one redesign is allowed on method-design, and it must address a documented
failure class rather than individual claim IDs. Validation is opened only after this decision.

## Required reporting

- Per-model/per-condition accuracy, macro-F1, paired gains/regressions, and exact McNemar tests.
- Endpoint oracle and generative repairs beyond that oracle.
- Action counts, direct-recall/inference/insufficient-check profiles, and proposition consistency.
- Current Stage C, equal-call direct control, and model-only/RAG endpoints.
- Calls, tokens, latency, clean loss, and activation rate.

## Outcome

On Llama method-design at 1%, proposition v2 reaches 34/44, above poisoned RAG at 29/44,
same-model closed-book at 31/44, and the seven-call direct control at 32/44. Clean accuracy is only
38/60 versus clean RAG at 44/60, so the preregistered clean gate fails. The workflow is retained as
a negative ablation and was not tuned further after gold was joined. The simpler frozen Stage C is
the validation candidate; see `docs/STAGE4_FINAL_RESULTS.md`.
