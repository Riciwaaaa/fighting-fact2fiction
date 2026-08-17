# Stage 1 artifact inventory

Generated model payloads are intentionally Git-ignored, but they are not disposable. The Stage 1
layout keeps raw responses, resumability metadata, and evaluation products separate so later stages
can reuse exact endpoint outputs without provider calls.

| Artifact | Location | Purpose |
|---|---|---|
| Per-call immutable cache | `artifacts/cache/llm/entries/<prefix>/<key>.json` | Exact request, raw and parsed response, provider response/model IDs, token usage, latency, creation time, and inference-only metadata |
| Active coverage manifests | `artifacts/runs/stage1/<split>/internal_endpoint/<model>.json` | Claim/seed-to-cache-key mapping, exact config/prompt digests, failures, and output-contract status |
| Superseded manifests | `artifacts/runs/stage1/<split>/internal_endpoint/history/` | Prior scope mappings retained when a split grows or changes |
| Run audit | `artifacts/runs/stage1/<split>/internal_endpoint/audit.json` | Coverage, cache integrity, artifact digests, finish reasons, provider IDs, aggregate tokens, and latency distribution |
| Gold-joined summary | `artifacts/evaluation/stage1_internal_<split>.json` | Per-claim predictions and aggregate endpoint/ensemble metrics; evaluation use only |
| Task matrices | `artifacts/runs/stage1/task_matrix/` | Complete internal and RAG task identities for each execution tier |
| Split labels | `artifacts/evaluation/stage1_labels.json` | Gold labels isolated from inference code and prompts |
| Official selected evidence | `artifacts/data/averitec/` | Source archive hash, selected resource pools, GTE indexes, and counts |
| RAG endpoint traces | `artifacts/runs/stage1/<split>/rag_traces/` | Questions, query results, ranks/distances, evidence excerpts, answers, verdict, cache receipts |
| Poison corpora | `artifacts/runs/stage1/<split>/poison_corpora/` | Victim-aware plans, exact expanded documents, targets, and cached poison embeddings |
| Clean eligibility | `artifacts/evaluation/stage1_rag_clean_eligibility.json` | Per-victim Fact2Fiction clean-correct filter |
| Initial scan metrics | `artifacts/evaluation/stage1_fact2fiction_initial_scan.json` | Accuracy, attack success, retrieval exposure, and realized budgets at four rates |
| Endpoint complementarity | `artifacts/evaluation/stage1_endpoint_complementarity.json` | Same-model and multi-model internal/RAG contingency tables, oracles, rescue rates, and micro-averages |
| Intermediate-rate scan | `artifacts/evaluation/stage1_rag_v1.2_intermediate_rate_scan_v1.json` | Audited 0.25%, 0.5%, and 0.75% endpoint results on all 227 eligible victim/claim pairs |
| Combined rate curve | `artifacts/evaluation/stage1_rag_v1.2_combined_rate_curve_v1.json` | Reproducible seven-rate per-model and pooled endpoint curve, panel baseline, selection headroom, exposure, and adjacent-rate transitions |
| Passage-signal freeze and amendment | `configs/evidence_signal_v1_{freeze,amendment_1}.json` | Pre-output endpoint-hidden passage protocol and pre-gold structured-contract repair |
| Passage-signal immutable run | `artifacts/runs/evidence_signal/evidence_signal_v1/` | 159 cached claim plans, 363 endpoint-hidden passage maps, visible packets, private join manifest, failures, and passed audit |
| Passage-signal evaluation | `artifacts/evaluation/evidence_signal_v1.json` | Whole-system projections, switch audits, grouped probes, per-model/rate results, and private poison-exposure diagnostics |
| Low-rate endpoint/answerability diagnostics | `artifacts/evaluation/{low_rate_aggregation_diagnostic,answerability_cascade}_v1.json` | Claim-grouped endpoint calibration, exact answerability cascade, full-system projections, and private reusable row joins |
| Retrospective calibrated-router transfer | `configs/calibrated_router_transfer_v1_freeze.json`, `artifacts/evaluation/calibrated_router_transfer_v1.json` | Shared endpoint-only logistic router and explicitly non-confirmatory transfer to previously opened locked artifacts |
| Counter-retrieval freeze | `configs/counter_retrieval_signal_v2_freeze.json` | Pre-map exclusion semantics, scope, prompts, code hashes, and preserved superseded no-call pilot |
| Counter-retrieval immutable run | `artifacts/runs/counter_retrieval/counter_retrieval_signal_v2/` | 363 leave-original-out retrievals, endpoint-hidden packets, same-model maps, receipts, manifests, and passed audits |
| Counter-retrieval evaluation | `artifacts/evaluation/counter_retrieval_signal_v2.json` | Typed answerability-plus-corroboration result, per-model/rate projections, switches, grouped probes, and claim-clustered uncertainty |
| Frozen corroboration controller | `configs/corroboration_arbiter_v1_freeze.json`, `artifacts/runs/corroboration_arbiter/corroboration_arbiter_v1/` | 363 pre-audited same-model controller packets, cached three-action outputs, exact prompt reconstruction, usage, and final audit |
| Controller/fusion ablations | `artifacts/evaluation/{corroboration_arbiter_v1,counter_endpoint_fusion_oof_v1}.json` | Frozen raw/guarded LLM controller and claim-grouped endpoint-calibration fusion, both negative against the typed counter rule |
| Three-model corroboration plus | `artifacts/evaluation/multimodel_corroboration_plus_v1.json` | Secondary cached panel override, per-model/rate accuracy, and complete override records |
| Selected low-rate candidate | `configs/low_rate_corroboration_candidate_v1.json` | Post-development candidate provenance, exact primary/plus policies, source/result hashes, controls, and fresh-confirmation gates |
| Query-aligned trace feasibility | `configs/query_aligned_trace_feasibility_v1.json`, `artifacts/evaluation/query_aligned_trace_feasibility_v1.json` | Frozen distinction between poison exposure and poison selected into the final judge record, with per-model/rate diagnostics and follow-up gates |
| Query-aligned internal replay | `configs/query_aligned_internal_replay_v1.json`, `artifacts/runs/query_aligned/query_aligned_internal_replay_v1/` | Two cached same-model closed-book answers to each exact RAG question plan, reused across poisoning conditions |
| Query-aligned conflict maps | `configs/query_aligned_conflict_map_v1{,_amendment_1,_amendment_2,_amendment_3}.json`, `artifacts/runs/query_aligned/query_aligned_conflict_map_v1/` | Same-model semantic comparison of two internal answers with each RAG answer, 304 unique packets expanded to 363 rows |
| Fixed-context conflict intervention | `configs/query_aligned_intervention_v1.json`, `artifacts/runs/query_aligned/query_aligned_intervention_v1/` | 165 answer and verdict reruns after global suspect-document removal from existing retrievals, with no retrieval or backfill |
| Query-aligned evaluations | `artifacts/evaluation/query_aligned_{conflict_map,intervention}_v1.json` | Conflict-risk/provenance diagnostics, intervention policies, full-system projections, paired changes, and claim-clustered uncertainty |
| Localized conflict development candidate | `configs/query_aligned_localized_candidate_v1.json` | Post-label repeated-but-localized causal gate, explicit provenance warning, and fresh-confirmation requirements |
| Fixed-context RAG stress run | `configs/rag_cluster_stress_v1{,_amendment_1}.json`, `artifacts/runs/rag_stress/rag_cluster_stress_v1/` | 1,007 fixed-retrieval stress views over 925 unique contexts, with no retrieval or backfill and complete cached answer/verdict outputs |
| Frozen stress selectors | `configs/rag_stress_arbiter_v1.json`, `artifacts/runs/rag_stress_arbiter/rag_stress_arbiter_v1/` | 227 matched-control and 227 stress-informed same-model selectors over opposing binary endpoint disagreements |
| RAG stress evaluations | `artifacts/evaluation/{rag_stress_arbiter,rag_stress_rescue_oof}_v1.json` | Negative frozen-selector result and post-label nested claim-grouped conservative-rescue diagnostic |
| Environment-drift protocol | `configs/environment_drift_gate_v1{,_amendment_1,_amendment_2}.json` | Clean-calibrated detector, tiered evidence policy, and rate scopes recorded before each new counter-evidence collection |
| Environment-drift implementation/tests | `src/parametric_rag_defense/environment_drift.py`, `tests/test_environment_drift.py` | Gold-free Beta-binomial disagreement statistic and normal/warning/critical typed routing policy |
| Rate-extension source evidence | `artifacts/runs/evidence_signal/evidence_signal_{rate075_1pct,rate4_8pct}_v1/` | Cached same-model claim plans and original-view evidence reports for all 540 new endpoint disagreements, with passed audits |
| Rate-extension counter evidence | `artifacts/runs/counter_retrieval/counter_retrieval_{rate075_1pct,rate4_8pct}_v1/` | Leave-original-out retrievals and same-model reports for all 540 rows, including deliberately poisoned high-rate counter views |
| Environment-conditioned evaluations | `artifacts/evaluation/{environment_drift_gate_v1,tiered_environment_policy_high_rate_v1}.json` | Detection transfer, complete clean-to-8% policy curve, per-model cells, paired changes, and claim-clustered intervals |
| Selected two-scale candidate | `configs/environment_conditioned_candidate_v1.json` | Exact claim/environment policies, development boundary, immutable hashes, limitations, and fresh-confirmation gate |
| Environment-conditioned report | `docs/ENVIRONMENT_CONDITIONED_RESULTS.md` | Plain-language method, full results, high-rate safety ablation, limitations, and fresh-confirmation protocol |
| Matched top-10 RAG diagnostic | `configs/rag_top10_confirmation_diagnostic_v1.json`, `artifacts/runs/rag_top10_confirmation_v1/`, `artifacts/evaluation/rag_top10_confirmation_v1/` | Opened-confirmation control that reuses the exact top-5 questions, poison corpora, and attacked scope while doubling retrieved documents per subquestion; includes paired results and a passed cache/scope/contract audit |
| Intermediate-rate audit | `artifacts/runs/stage1/development/rag/stage1_rag_v1.2/intermediate_rate_scan_v1_audit.json` | Scoped reconstruction of 981 clean-plus-new-rate endpoints and 2,461 referenced cache entries |
| RAG scan audit | `artifacts/runs/stage1/development/rag_scan_audit.json` | Expected-task reconstruction, artifact canonicality, cache integrity, token usage, and manifest hashes |
| Superseded RAG smoke | `artifacts/runs/stage1/development/history/pre_v1.1_smoke/` | Pre-v1.1 endpoint/trace artifacts retained outside the active result namespace |
| Same-model A/B packets and routers | `artifacts/runs/stage3/stage3_same_model_ab_v1/` | Immutable endpoint-only/evidence-aware packets, router outputs, and private routing manifest |
| Same-model Stage C checks/selectors | `artifacts/runs/stage4/stage4_same_model_c_v1/` | Immutable pivotal-proposition checks, final endpoint selections, and private routing manifest |
| Same-model offline summaries | `artifacts/evaluation/stage{3_same_model_ab,4_same_model_c}_v1.json` | Per-model clean/attacked endpoints, oracle, routing outcomes, exact paired tests, and success gates |
| Frozen candidate manifest | `configs/stage4_candidate_freeze.json` | Model, workflow, seeds, decoding, activation, success evidence, and SHA-256 hashes fixed before validation |
| Validation Stage 2/3/4 runs | `artifacts/runs/stage{2/stage2_signal_validation,3/stage3_same_model_validation,4/stage4_same_model_validation}_v1/` | Sanitized validation packets, frozen Llama routers, targeted checks/selectors, manifests, and audit targets |
| Exact-budget generic controls | `artifacts/runs/stage{3/stage3_same_model_generic_control_{design,validation},4/stage4_generic_control_{design,validation}}_v1/` | Derived generic-proposition routers and otherwise matched two-call Stage C ablations |
| Consolidated Stage 4 study | `artifacts/evaluation/stage4_final_study.json` | Split/condition metrics, exact paired tests, treatment/control cases, activation/action profiles, and token/latency accounting |
| Frozen 0.1% extension | `artifacts/runs/stage{3,4}/stage{3,4}_same_model_rate001_{design,validation}_v1/` | Cached clean and new low-rate routers, targeted checks/selectors, manifests, and one-shot validation artifacts |
| 0.1% extension evaluations | `artifacts/evaluation/stage4_same_model_rate001_{design,validation}_v1.json` | Per-model endpoints, Stage C accuracy, oracle headroom, paired exact tests, and frozen success gates |
| Crossed attacker-victim endpoints | `artifacts/runs/stage1/development/rag/stage1_crossed_av_1pct_v1/` | Full 3×3 1% matrix, exact reused poison provenance, private retrieval traces, immutable endpoints, and coverage manifest |
| Crossed attacker-victim evaluation | `artifacts/evaluation/stage1_crossed_av_1pct_v1.json` | Per-cell accuracy, ASR, retrieval exposure, same-model closed-book/oracle headroom, paired tests, and attacker/victim aggregates |
| Crossed Stage 2 defense packets | `artifacts/runs/stage2/stage2_crossed_defense_v2/` | All 849 attacker-hidden visible packets, private attacker/victim join index, immutable endpoint links, and coverage manifest |
| Crossed Stage 3/4 defense outputs | `artifacts/runs/stage{3,4}/stage{3,4}_crossed_defense_v2/` | Same-model router outputs plus 357 retrieval-isolated proposition checks and endpoint selectors over the full crossed matrix |
| Crossed Stage C evaluation | `artifacts/evaluation/stage4_crossed_defense_v2.json` | Clean, per-cell, per-victim attacker-aggregated, endpoint-oracle, paired-test, claim-clustered interval, and frozen-gate results |
| Stage 5 neutral-firewall freeze | `configs/stage5_neutral_firewall_freeze.json` | Pre-output claim-only planning, dual retrieval-isolated checks, exact-call direct control, rationale firewall, scope, hashes, and gates |
| Stage 5 immutable outputs | `artifacts/runs/stage5/stage5_neutral_firewall_v1/` | Cached plans/checks/selectors, 714 row-level outputs, private descriptor manifest, and resumable progress ledger |
| Stage 5 original evaluation | `artifacts/evaluation/stage5_neutral_firewall_v1.json` | Literal frozen-selector metrics, per-cell results, controls, paired tests, clustered intervals, and failed gate |
| Stage 5 semantic correction | `configs/stage5_strict_policy_correction.json` | Post-label provenance and exact implementation of the retrieval-convergence condition already stated in the frozen selector prompt |
| Stage 5 diagnostic/strict evaluation | `artifacts/evaluation/stage5_neutral_firewall_{diagnostic,strict}_v1.json` | Selector-policy failure analysis and non-confirmatory policy-enforced metrics with no new inference calls |
| Extension freezes | `configs/{stage4_rate_extension,crossed_av_execution}_freeze.json` | Pre-output design decisions, expected coverage, immutable method hashes, and transparent post-collection offline-analysis record |
| Crossed defense freeze | `configs/crossed_defense_freeze.json` | Attacker-hidden protocol, model/decoding roles, success gate, immutable hashes, and recorded adapter/parser deviations |
| Locked confirmation freeze/amendments | `configs/stage5_locked_confirmation_{freeze,amendment_1,amendment_2,amendment_3,amendment_4}.json` | Pre-output scope, gates, stopping rule, and every pre-gold operational deviation |
| Locked clean/crossed endpoints | `artifacts/runs/stage1/locked_test/` | 300 clean endpoints, 693 complete 3×3 attacked endpoints, poison plans, traces, and eligibility records |
| Locked attacker-hidden inputs | `artifacts/runs/stage3/stage3_locked_neutral_inputs_v1/` | 993 audited packets and private condition/victim provenance |
| Locked Stage 5 outputs | `artifacts/runs/stage5/stage5_locked_neutral_firewall_v1/` | 780 row descriptors, immutable workflow/control outputs, fail-closed receipts, and final zero-failure manifest |
| Locked confirmation evaluation | `artifacts/evaluation/stage5_locked_neutral_firewall_v1.json` | One-time gold join, clean/per-cell/per-victim metrics, paired tests, clustered intervals, frozen gates, and mandatory sensitivity |

The cache key commits to the provider, model, exact messages, prompt identity and digest, decoding
parameters, response format, seed, stage, and cache schema version. The adjacent tracked prompt
digest (`prompts/internal_claim_v2.md.sha256`) additionally stops accidental whitespace edits before
they create a second cache namespace.

The active primary design uses 100 balanced binary development claims and 100 disjoint balanced
binary locked claims, with exact normalized claim/date prompts unique across every partition.
Historical outputs from the earlier 50-claim four-label development scope and the pre-deduplication
100-claim scope are
still represented by archived manifests and immutable cache entries. Its 20 conflict/NEI claims
are named in `configs/splits/stage1.json` as `four_label_diagnostic`.

To verify and summarize an already collected development run without making calls:

```bash
PYTHONPATH=src python3 scripts/check_stage1_internal.py
PYTHONPATH=src python3 scripts/audit_stage1_internal.py
PYTHONPATH=src python3 scripts/summarize_stage1_internal.py \
  --output artifacts/evaluation/stage1_internal_development.json
```

These commands read manifests and cache entries only. `run_stage1_internal.py` is the sole command
in this sequence that can contact a provider.

To validate and summarize the completed RAG scan without provider calls:

```bash
.venv/bin/python scripts/check_stage1_rag_scan.py
.venv/bin/python scripts/summarize_stage1_rag_scan.py
```
