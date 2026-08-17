# Parametric RAG Defense

Research code for testing whether LLM internal knowledge can improve robustness to retrieval-corpus
poisoning. The project compares model-only and poisoned-RAG endpoints, claim-level LLM arbitration,
targeted subquestion escalation, and same-model versus cross-model workflows.

The full study design and success criteria are in [RESEARCH_PLAN.md](RESEARCH_PLAN.md).

## Current status

The fresh 100-claim confirmation is complete and positive. The frozen environment-conditioned
policy reaches **80.48%** over 1,260 attacked rows, versus poisoned RAG at 48.97% and three-call
same-model closed book at 73.02%, while scoring 83.67% on 300 clean rows versus clean RAG at
84.00%. It beats both raw attacked endpoints when pooled separately for GLM, Llama, and Qwen. A
prespecified two-attacker 1% transfer secondary reaches **83.09%** over 414 rows, versus RAG at
58.94% and closed book at 76.33%. All endpoint, exclusion, same-model, prompt-isolation, cache, and
response-contract audits pass. See
[docs/ENVIRONMENT_CONFIRMATION_RESULTS.md](docs/ENVIRONMENT_CONFIRMATION_RESULTS.md) and the frozen
[primary](configs/environment_confirmation_protocol_v1.json) and
[transfer](configs/environment_attacker_transfer_v1.json) protocols.

A matched top-10-per-subquestion RAG diagnostic is also complete. Doubling the raw retrieval budget
improves attacked RAG from 48.97% to **53.33%** and clean RAG from 84.00% to **85.33%**, but remains
far below three-call model-only at 73.02%, the answerability fallback at 80.16%, and the proposed
method at 80.48% on the identical 1,260 attacked rows. This strengthens the attribution to internal
knowledge rather than merely more retrieved material. The confirmation set was already open, so
this is a diagnostic rather than independent validation. See
[docs/RAG_TOP10_BASELINE_RESULTS.md](docs/RAG_TOP10_BASELINE_RESULTS.md).

Stage 1 v1.2 is complete: three NVIDIA production models produced 900/900 model-only outputs,
300/300 metadata-neutral clean RAG endpoints, and 908/908 attacked endpoints at 0.1%, 1%, 4%, and
8%. The independent audit found no missing, unexpected, contract, poison-material, or victim-prompt
leakage failure. Stage 2 built and audited 732 sanitized packets on a frozen 60-claim method-design
partition. Stage 3 completed 318 evidence critiques and 636 claim-arbiter outputs for clean plus 1%.
It beats poisoned RAG but **does not beat the strongest model-only endpoint**, so it is recorded as
a negative design result. The
development-endpoint credential for Qwen 397B is still unavailable.

The active redesign is a strict per-model A/B/C experiment: the same model produces its RAG
endpoint, three-repeat closed-book endpoint, router, and targeted proposition check. It removes the
three-model candidate panel and fixed Qwen critic from the primary experiment. See
[docs/ALIGNED_SAME_MODEL_PROTOCOL.md](docs/ALIGNED_SAME_MODEL_PROTOCOL.md).

The method-design A/B/C run is complete. For Llama 3.1 70B, Stage C reaches 35/44 (79.5%) at
1% poisoning, above both Llama closed-book at 31/44 and Llama RAG at 29/44, while clean accuracy is
43/60 versus clean RAG's 44/60. The frozen workflow then reaches **23/28 (82.1%)** on one-shot 1%
development-validation, above same-model closed-book at 16/28 and poisoned RAG at 21/28; its paired
gain over model-only is 7--0 (exact p=0.0156). Clean is 27/40 versus RAG's 28/40. GLM and Qwen do not
pass the design gate, so the result remains model-conditional and workshop-level. See
[docs/STAGE4_FINAL_RESULTS.md](docs/STAGE4_FINAL_RESULTS.md).

The frozen 0.1% extension did not yield a second confirmed model: GLM and Llama passed design, but
GLM tied model-only and Llama fell one case below RAG on one-shot validation. See
[docs/RATE_EXTENSION_RESULTS.md](docs/RATE_EXTENSION_RESULTS.md).

A frozen 1% crossed attacker-victim diagnostic completed all 549 rows. It shows that the original
diagonal was strongly confounded by poison-generator identity: GLM poison has 60.7% mean ASR across
victims, Qwen poison 46.4%, and Llama poison 18.0%. Llama's apparently robust same-model RAG falls
to 36.1% under GLM-generated poison, while GLM is the most robust victim averaged across attackers.
See [docs/CROSSED_ATTACKER_VICTIM_RESULTS.md](docs/CROSSED_ATTACKER_VICTIM_RESULTS.md).

The unchanged Stage C workflow has now been applied to that full matrix. Aggregated over all three
attackers, it beats both same-model endpoints for GLM (157/183 versus model-only 153 and RAG 124)
and Llama (127/183 versus 120 and 98), satisfying the frozen two-victim practical gate. Qwen misses
by one attacked case and four clean points. The result is still exploratory: claim-clustered
intervals versus model-only include zero, and under the strongest GLM poison Stage C is 131/183
versus model-only 139/183. See
[docs/CROSSED_DEFENSE_RESULTS.md](docs/CROSSED_DEFENSE_RESULTS.md).

A subsequent neutral, rationale-firewalled four-call workflow completed the same clean-plus-crossed
matrix with a matched direct-call control. Its unconstrained LLM selector failed the frozen gate
(415/549 attacked versus closed-book 417). A post-label audit found that the implementation had not
enforced the prompt's predeclared two-check convergence requirement for retrieval. Enforcing that
semantic contract with no new calls gives an **exploratory** 423/549 versus closed-book 417, direct
control 416, and poisoned RAG 320; GLM and Qwen pass the practical per-victim gate, and the method is
140/183 versus closed-book 139 under the strongest GLM attacker. Because this correction was
diagnosed after labels were opened, it requires untouched held-out confirmation. See
[docs/NEUTRAL_FIREWALL_RESULTS.md](docs/NEUTRAL_FIREWALL_RESULTS.md).

The untouched 100-claim locked confirmation is now complete, and it is negative. Over the complete
3×3 attacker-victim matrix (693 attacked rows), the strict workflow reaches 554 correct versus
same-model closed-book at 561, the exact-call direct control at 563, and poisoned RAG at 396. No
victim passes the frozen attacked-win plus clean-utility gate; under GLM-generated poison, strict is
181/231 versus model-only at 187/231. The mandatory Qwen-264 exclusion changes no conclusion. The
workflow will not be tuned on this split. See
[docs/LOCKED_CONFIRMATION_RESULTS.md](docs/LOCKED_CONFIRMATION_RESULTS.md).

A subsequently frozen development-only endpoint scan fills the low-rate gap with 0.25%, 0.5%, and
0.75% poisoning. All 681 new outputs passed audit. On the identical 227 eligible victim/claim
pairs, RAG scores 182, 177, 151, 132, and 113 correct at 0.1%, 0.25%, 0.5%, 0.75%, and 1%, while
same-model closed-book remains 175 and the three-model panel remains 192. The meaningful blend
regime is therefore 0.1%--0.25%; stronger rates increasingly favor internal knowledge. This is
method-development evidence, not a new confirmation result. See
[docs/INTERMEDIATE_RATE_SCAN_RESULTS.md](docs/INTERMEDIATE_RATE_SCAN_RESULTS.md).

The first low-rate evidence-signal experiment is also complete. It collected 363 endpoint-hidden
passage maps with zero audit failure. A strict retrieval-default diagnostic reaches 184/227 at
0.1%, just above RAG at 182 and closed book at 175, but the gain is only two switched claims and
does not persist at 0.25%. More importantly, on attacked exclusive disagreements a strict evidence
direction agrees with RAG 48 times and is wrong in 41: fluent poisoned text is interpreted as
direct evidence rather than detected as fabricated. We therefore do not run another arbiter over
the same text alone. See [docs/EVIDENCE_SIGNAL_RESULTS.md](docs/EVIDENCE_SIGNAL_RESULTS.md) and the
revised [counter-retrieval plan](docs/COUNTER_RETRIEVAL_PLAN.md).

The counter-retrieval cycle is now complete and supplies the strongest development result. For
every endpoint disagreement, it excludes all original document IDs and exact texts, retrieves a
second view, and asks the same victim model for an endpoint-hidden evidence report. A typed rule
combines that report with the same model's closed-book answerability signal. It reaches **208/227,
210/227, and 202/227** at 0.1%, 0.25%, and 0.5%, above both poisoned RAG (182, 177, 151) and
same-model closed book (175 at each rate). It also beats both endpoints for each of GLM, Llama, and
Qwen individually. A frozen free-form LLM controller is worse, while a secondary cached
three-family plus variant reaches 212, 211, and 204. These are method-development results selected
on the current claims, not independent confirmation. See
[docs/COUNTER_RETRIEVAL_RESULTS.md](docs/COUNTER_RETRIEVAL_RESULTS.md) and
[configs/low_rate_corroboration_candidate_v1.json](configs/low_rate_corroboration_candidate_v1.json).

A query-aligned internal-knowledge follow-up is complete. The same victim answered each exact RAG
question twice without retrieval, then identified stable contradictions with the RAG answer. These
conflicts diagnose risky attacked traces (75.2% RAG error when flagged versus 38.8% when unflagged),
but blindly removing flagged evidence is harmful and the signal is nearly absent for Llama. A
post-label repeated-but-localized removal rule adds three development corrections and no regressions
to the selected method, projecting to 209/227, 211/227, and 203/227 at 0.1%, 0.25%, and 0.5%, with
clean unchanged at 244/300. The gains come from only two claims and the claim-clustered interval
includes zero, so the prior corroboration method remains selected and the extension requires fresh
confirmation. The intervention uses the original retrieved groups with no second retrieval. See
[docs/QUERY_ALIGNED_INTERNAL_RESULTS.md](docs/QUERY_ALIGNED_INTERNAL_RESULTS.md).

A subsequent fixed-context stress experiment is complete and negative. It reran RAG on 1,007
controlled subsets of the already retrieved context, without new retrieval or backfill, then gave
the same victim model either a matched control packet or the stress outcomes. The selected
corroboration method remains stronger: selected/control/stress counts are 244/242/241 clean,
208/203/204 at 0.1%, 210/204/199 at 0.25%, and 202/199/191 at 0.5%. Structural stress improves
post-label error-ranking AUC but supplies no attacked-set gain under conservative claim-grouped
selection. The next hypothesis is a two-scale controller that combines sealed claim-level memory
with a clean-calibrated environment-level retrieval-drift alarm. See
[the fixed-context stress results](docs/RAG_CLUSTER_STRESS_RESULTS.md).

That two-scale study is now complete on development data. It measures, for each victim model, how
often answerable three-call internal majorities disagree with RAG relative to a clean reference.
Normal environments use the selected leave-original-out blend, suspicious environments require
direct unopposed corroboration, and severely abnormal environments disable retrieval-based
overrides in favor of the memory-first answerability fallback. The policy never receives the
nominal rate, attacker, poison provenance, retrieved poison count, or gold.

Across the same 227 attacked rows, the proposed policy scores 208, 210, 202, 197, 191, 179, and 182
at 0.1%, 0.25%, 0.5%, 0.75%, 1%, 4%, and 8%. It beats both raw endpoints at every rate, although it
is one case below both simpler blend/fallback ablations at 1% and four below memory-first at 4%.
At 8%, all models enter severe mode: the policy reaches 182 versus model-only 175, poisoned RAG 51,
and always blending 127. The supposedly independent second retrieval is itself heavily poisoned
at high rates, so the gate prevents 55 errors and introduces none relative to always blending.
This supports an environment-conditioned method, but it is selected development evidence and still
needs genuinely fresh confirmation. See
[the environment-conditioned results](docs/ENVIRONMENT_CONDITIONED_RESULTS.md) and the frozen
[candidate manifest](configs/environment_conditioned_candidate_v1.json).

This repository is intentionally separate from `fighting-fact2fiction-main`. The previous project
is treated as a read-only source of exploratory artifacts and upstream integrations.

## Stage 1 commands

Run the standard-library test suite:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Regenerate the deterministic binary primary split and retained four-label diagnostic:

```bash
python3 scripts/make_stage1_split.py
```

Import the previous run as development-only, metadata-masked artifacts:

```bash
python3 scripts/import_legacy_stage1.py
python3 scripts/audit_legacy_complementarity.py
```

Validate Stage 1 request generation without making provider calls:

```bash
PYTHONPATH=src python3 scripts/run_stage1_internal.py --dry-run --claims 0
```

Build the complete model/strength task matrix:

```bash
PYTHONPATH=src python3 scripts/make_stage1_task_matrix.py
```

Prepare the official AVeriTeC store and run the matched clean/four-level RAG scan:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e '.[rag]'
.venv/bin/python scripts/prepare_stage1_kb.py
.venv/bin/python scripts/run_stage1_rag_scan.py --phase clean --workers 6
.venv/bin/python scripts/run_stage1_rag_scan.py --phase poison --workers 6
```

Evaluate a cached internal-model pilot or completed split:

```bash
PYTHONPATH=src python3 scripts/summarize_stage1_internal.py --claims 0,6,26,43
```

Smoke-test the configured NVIDIA endpoints:

```bash
PYTHONPATH=src python3 scripts/smoke_nvidia_models.py
```

Actual calls require `NVIDIA_API_KEY` in the process environment or Git-ignored `.env`. Cache
payloads and credentials are ignored by Git. The configuration covers PoisonedRAG `N=0..10` and
Fact2Fiction 0%–16% strength curves; retrieval-free outputs are cached once and reused across all
conditions.

See [docs/STAGE1_EXECUTION.md](docs/STAGE1_EXECUTION.md) for poisoning semantics, the normalized
RAG adapter contract, execution tiers, and locked-test safeguards.
The exact clean/initial-scan implementation and its deliberate preliminary approximations are in
[docs/STAGE1_RAG_SCAN_PROTOCOL.md](docs/STAGE1_RAG_SCAN_PROTOCOL.md).
Measured clean, attack-curve, retrieval-exposure, and endpoint-complementarity results are in
[docs/STAGE1_RAG_SCAN_RESULTS.md](docs/STAGE1_RAG_SCAN_RESULTS.md).
The corrected v1.2 results and audits are in
[docs/STAGE1_RAG_V12_RESULTS.md](docs/STAGE1_RAG_V12_RESULTS.md),
[docs/STAGE2_SIGNAL_RESULTS.md](docs/STAGE2_SIGNAL_RESULTS.md), and
[docs/STAGE3_CLAIM_ARBITER_RESULTS.md](docs/STAGE3_CLAIM_ARBITER_RESULTS.md). Operational artifact
boundaries and resume commands are in
[docs/STAGE234_EXECUTION.md](docs/STAGE234_EXECUTION.md).

The active three-model binary study is summarized in
[docs/STAGE1_DEVELOPMENT_RESULTS.md](docs/STAGE1_DEVELOPMENT_RESULTS.md); its historical four-label
predecessor is preserved in
[docs/STAGE1_FOUR_LABEL_DIAGNOSTIC.md](docs/STAGE1_FOUR_LABEL_DIAGNOSTIC.md). See
[docs/ARTIFACT_INVENTORY.md](docs/ARTIFACT_INVENTORY.md) for the raw-cache, manifest-history, audit,
and evaluation layout, and [docs/STAGE1_COLLECTION_LOG.md](docs/STAGE1_COLLECTION_LOG.md) for the
exact collection/repair/deduplication history. The matched endpoints establish defense headroom;
they do not yet constitute a deployable poisoning defense.
