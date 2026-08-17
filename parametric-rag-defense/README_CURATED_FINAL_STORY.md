# Curated artifacts: internal knowledge as a RAG safety anchor

This archive is the compact companion to the source snapshot
`parametric-rag-defense-git-567beb0-20260815.zip`. It retains the generated evidence needed to
inspect the final workshop-level story without packaging the 53 GB project artifact tree. The
source snapshot is commit `567beb0` and contains the code, prompts, frozen configurations, tests,
and full research log.

## The final story

The study asks when an LLM's internal knowledge can protect a RAG system whose shared corpus is
poisoned. The result is conditional rather than a claim that model-only answering always wins or
that individual poisoned passages can be reliably detected.

For each claim, the same victim model is called three times without retrieval. A deterministic
majority supplies an internal-memory answer; an answerability field says whether that answer should
be used. The ordinary RAG workflow independently produces its verdict. Across multiple queries to
the same corpus, the system monitors how often answerable internal memory disagrees with RAG,
relative to a model-specific clean reference frozen on development data.

- In a clean-like environment, retrieval can still add value. On endpoint disagreements, the
  workflow reuses the RAG-generated questions, excludes the documents and exact texts used by the
  first view, and retrieves a second view from the **same possibly poisoned corpus**. A structured
  same-model evidence report decides whether retrieval has independent support.
- Under moderate drift, retrieval needs stricter and unopposed corroboration.
- Under severe drift, retrieval is no longer allowed to overrule the internal anchor; the system
  uses the answerability-aware model-only fallback.

The defense never receives the nominal attack rate, attacker identity, poison labels, poison
counts, gold labels, or endpoint correctness. It is best understood as a policy for repeated
queries in a shared retrieval environment, not as a single-query poison detector.

## Fresh confirmation result

The method and thresholds were frozen before inference on a fresh balanced 100-claim AVeriTeC
subset. Only Supported/Refuted claims were used. Attacked evaluation follows Fact2Fiction's second
eligibility filter: a victim/claim pair is included only when that victim's clean RAG verdict is
correct.

Across 1,260 attacked rows (three victims and five nominal poisoning rates), the frozen policy
scores **80.48%**, versus **48.97%** for poisoned RAG and **73.02%** for three-call same-model
closed book. On 300 clean rows it scores **83.67%**, versus **84.00%** for clean RAG. Pooled across
rates, its point estimate beats both attacked endpoints separately for GLM 5.2, Llama 3.1 70B,
and Qwen 3.5 35B A3B.

The rate curve explains why the blend is conditional. The top-10 column is the matched
double-retrieval-budget control described in the next section:

| Nominal rate | Rows | Poisoned RAG (top-5) | Poisoned RAG (top-10) | Closed book | Proposed |
|---:|---:|---:|---:|---:|---:|
| 0.1% | 252 | 80.16% | 80.95% | 73.02% | **88.10%** |
| 0.5% | 252 | 71.43% | 71.83% | 73.02% | **84.52%** |
| 1% | 252 | 50.00% | 58.33% | 73.02% | **80.16%** |
| 4% | 252 | 25.00% | 32.54% | 73.02% | **75.00%** |
| 8% | 252 | 18.25% | 23.02% | 73.02% | **74.60%** |

At low rates the same-corpus second view adds useful information. At high rates it is also heavily
poisoned, so the environment warning turns retrieval overrides off. The online, prior-observations-
only simulation scores 76.59%, which is above both raw endpoints but below the 80.48% batch-end
result because detection needs a warm-up period.

A prespecified two-attacker 1% transfer test contains 414 rows and scores **83.09%**, versus
**58.94%** for poisoned RAG and **76.33%** for closed book. This reduces, but does not eliminate,
concern that the result depends on using the same model as poison generator and victim.

## Matched double-retrieval-budget control

The proposed method reads more retrieved material than a single top-5 RAG pass, so the natural
objection is that its advantage is simply a larger retrieval budget rather than internal knowledge.
The `rag_top10_confirmation_v1` diagnostic answers that objection directly: it reuses the exact
original question plans, poison documents and embeddings, condition prefixes, victims, prompts,
decoding, evidence truncation, and top-5 clean-correct eligibility, and changes only the number of
retrieved documents per subquestion from five to ten. The top-10 endpoint never sees a closed-book
answer, an answerability signal, a disagreement or environment state, a gold label, an attacker
identity, or poison provenance. All 300 clean and 1,260 attacked endpoints completed with zero
failures.

| Scope | Rows | Top-5 RAG | Top-10 RAG | Model-only | Answerability fallback | Proposed |
|---|---:|---:|---:|---:|---:|---:|
| Clean | 300 | 84.00% | **85.33%** | 68.67% | 82.00% | 83.67% |
| Attacked | 1,260 | 48.97% | 53.33% | 73.02% | 80.16% | **80.48%** |

Doubling the budget is a real improvement for ordinary RAG on attacked rows: 105 exclusive correct
cases versus 50, a net 4.37 points with exact paired p = 1.18e-5. The clean change is not resolved
(12 gains, eight losses, p = 0.503). But top-10 RAG still trails same-model closed book by 19.68
points and the proposed method by 27.14 points, and its gain is smallest precisely in the low-rate
regime where the blend wins most. Even an oracle that picks the better of top-5 and top-10 per row
reaches only 57.30% on attacked rows, so the two budgets do not hold enough complementary correct
predictions to approach the internal endpoints.

Retrieval exposure explains the shape of the gain. Top-10 retrieves more poison documents in
absolute terms (19,730 versus 15,518) but many more documents overall, lowering the poison fraction
from 57.76% to 46.25%. Dilution helps, but does not make retrieval safe: at 8% nominal poisoning,
88.88% of retrieved documents are poison and accuracy is 23.02%.

Two consequences for the write-up: top-10 should replace top-5 as the strongest raw-RAG comparator
where a single strongest baseline is reported, and the remaining exact-union ablation — one joint
interpretation of the same top-10 documents versus two separate top-5 interpretations — is what
would isolate evidence partitioning from internal knowledge. Like the confirmation set itself, this
control was run after the confirmation claims were opened, so it is a diagnostic rather than
independent validation; its protocol was nonetheless frozen before any top-10 endpoint call.

## Important limitations

- The confirmation set contains 100 independent claims from a public benchmark.
- The attack is non-adaptive; it does not target the internal anchor or drift statistic.
- The strongest result uses a batch-level environment state. Online detection is weaker during
  warm-up.
- The clean-utility gate is pooled; GLM loses four clean points even though Llama and Qwen do not.
- Qwen's pooled advantage over closed book is small and statistically unresolved.
- At 1%, the simpler answerability fallback is one case above the full proposed method.
- The second retrieval is not clean or trusted. It uses the same attacked corpus and is disabled
  when corpus-level disagreement becomes severe.
- The top-10 control equalises the retrieval budget but not the evidence structure: the proposed
  method still interprets two separately retrieved views. The exact-union ablation that would
  separate partitioning from internal knowledge has not been run.
- The top-10 control is an opened-confirmation diagnostic. It shares the confirmation claims and
  therefore cannot serve as independent validation.
- The opened confirmation claims must not now be tuned and re-reported as independent validation.

## What is included

### Fresh-confirmation raw cache

`cache/llm_environment_confirmation_train_v1/entries/` contains all 7,098 content-addressed request
records used by the confirmation and attacker-transfer runs. The records retain exact messages,
raw and parsed model responses, model/provider identifiers, usage, latency, and format-repair
attempts. Empty cache-lock bookkeeping is deliberately omitted.

### Fresh-confirmation run traces

`runs/environment_confirmation_train_v1/` contains endpoint manifests, RAG traces, poison-corpus
manifests, evidence packets and outputs, leave-original-out retrieval records, source packets,
counter-view outputs, receipts, progress state, and the four audit files. Together with the cache,
these files allow later error analysis without repeating the 23.1-million-token inference run.

### Fresh-confirmation evaluations

`evaluation/environment_confirmation_train_v1/` contains:

- `endpoint_summary.json`: clean and attacked endpoint rows;
- `environment_conditioned_results.json`: complete primary result, states, ablations, paired tests,
  uncertainty estimates, and per-row decisions;
- `attacker_transfer_results.json`: complete crossed-attacker secondary;
- `internal_summary.json`: three-call closed-book summaries;
- clean-eligibility and initial-scan files.

### Double-retrieval-budget control

The top-10 diagnostic is retained in full, in its own isolated namespace so it can never be
confused with the top-5 confirmation run:

- `cache/llm_rag_top10_confirmation_v1/entries/`: all 3,043 content-addressed request records for
  the top-10 answers and verdicts, with exact messages, raw and parsed responses, model identifiers,
  usage, and latency. Lock bookkeeping is omitted as elsewhere.
- `runs/rag_top10_confirmation_v1/`: all 1,560 endpoints and 1,560 private traces, plus manifests
  and progress state, under
  `stage1/confirmation/rag/rag_top10_confirmation_v1/`.
- `evaluation/rag_top10_confirmation_v1/`: `paired_results.json` (the complete paired comparison
  against top-5 RAG, model-only, the answerability fallback, and the proposed method, including
  per-rate, per-victim, oracle, and retrieval-exposure breakdowns), `audit.json` (passed scope,
  cache, and contract audit), `frozen_top5_attack_scope.json` (the frozen attacked scope inherited
  from the top-5 run), the clean-eligibility file, and the raw top-10 endpoint summary.

### Policy-development summaries

The top-level `evaluation/` files retain the compact evidence used to select and freeze the final
policy:

- `stage1_rag_v1.2_intermediate_rate_scan_v1.json` and
  `stage1_rag_v1.2_combined_rate_curve_v1.json`: endpoint behavior across rates;
- `stage1_rag_v1.2_intermediate_rate_complementarity_v1.json`: endpoint overlap/headroom;
- `counter_retrieval_signal_v2.json`: the low-rate leave-original-out blend;
- `environment_drift_gate_v1.json`: the corpus-level disagreement signal;
- `tiered_environment_policy_v1.json` and `tiered_environment_policy_high_rate_v1.json`: the frozen
  environment-conditioned policy and full development curve;
- `tiered_environment_policy_high_rate_v1.stdout`: retained evaluator output.

## Where to start

1. Read `docs/ENVIRONMENT_CONFIRMATION_RESULTS.md` in the source snapshot for the full tables,
   statistical tests, fairness checks, and limitations.
2. Inspect `evaluation/environment_confirmation_train_v1/environment_conditioned_results.json`
   for the machine-readable primary result.
3. Read `docs/RAG_TOP10_BASELINE_RESULTS.md` and `docs/RAG_TOP10_BASELINE_PROTOCOL.md` in the
   source snapshot for the double-retrieval-budget control, then
   `evaluation/rag_top10_confirmation_v1/paired_results.json` for its machine-readable form.
4. Inspect the audit files under `runs/environment_confirmation_train_v1/` and
   `evaluation/rag_top10_confirmation_v1/audit.json` before using raw rows.
5. Use the frozen configs and evaluation scripts from the source snapshot at commit `567beb0`;
   the top-10 control is reproducible from `configs/rag_top10_confirmation_diagnostic_v1.json`
   with `scripts/run_rag_top10_diagnostic.py`, `scripts/evaluate_rag_top10_diagnostic.py`, and
   `scripts/check_rag_top10_diagnostic.py`.
6. Use the request cache and run traces for qualitative examples or error analysis; no new model
   calls are required for those tasks.

## What is intentionally omitted

The package excludes downloaded AVeriTeC archives, extracted corpus copies, embedding indexes,
global development caches, legacy imports, and superseded exploratory methods. Those account for
nearly all of the original 53 GB tree and are not needed to inspect or re-evaluate the final
confirmation. The public data/index layer can be regenerated with the source snapshot if retrieval
must be rerun. `.env`, API credentials, virtual environments, and cache lock files are never
included.
