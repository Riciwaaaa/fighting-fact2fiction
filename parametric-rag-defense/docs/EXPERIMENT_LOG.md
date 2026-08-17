# Experiment progress log

This is the concise human-readable record of what was attempted, why, and what changed. Runtime
counters are available through `scripts/show_experiment_progress.py`; detailed immutable payloads
remain under `artifacts/`.

## 2026-08-09 — Stage 1 v1.1 completed, then superseded

- Completed 300 clean and 936 attacked endpoints at 0.1%, 1%, 4%, and 8%.
- Observed a clear poisoning curve and substantial RAG/internal complementarity.
- During Stage 3 packet design, found that victim answer prompts contained source IDs such as
  `clean:17` and `poison:3`. This exposes document origin and violates the intended threat model.
- Decision: retain v1.1 as directional exploration, exclude it from Stage 3, implement v1.2 with
  neutral source IDs and prompt-level leakage auditing, and recompute eligibility and attacks.

## 2026-08-09 — Stage 1 v1.2 initialized

- Added tracked experiment registry and a durable snapshot plus append-only event ledger.
- Planned order: metadata repair → clean rebuild → eligibility → attack rebuild → four-level scan →
  Stage 2 packets/diagnostics → Stage 3 clean/1% pilot.
- Locked claims remain unopened.

## 2026-08-09 — Stage 1 v1.2 completed and audited

- Completed 300 clean and 908 attacked endpoints; two Qwen answer-format failures were repaired
  through additional versioned retries, then the entire matrix was replayed from cache.
- Audit passed 1,208/1,208 endpoints and 2,946 referenced victim calls with no prompt metadata leak.
- At 1%, poisoned RAG reached 49.8%, the memory ensemble 84.6%, and their oracle 96.5%.

## 2026-08-09 — Stage 2 packets and signal characterization completed

- Froze a claim-grouped 60-design / 40-validation balanced split without using endpoint outcomes.
- Built and audited 732/732 sanitized design packets across clean and four attack levels.
- On the 138-pair 1% design subset, RAG reached 44.9%, memory ensemble 83.3%, and oracle 92.0%.
- The 40 validation claims and original locked test remain unopened.

## 2026-08-09 — Stage 3 v1 completed; success gate failed

- Completed 318 critics and 636 arbiter outputs for clean plus 1%; final cache replay and prompt
  isolation audit passed.
- Qwen arbiter was the better workflow at 1% (74.6%) but remained below GLM memory-only (84.8%).
- Diagnostic: its 38 overrides produced 8 gains and 22 regressions. High confidence and strong
  retrieval coverage did not make overrides reliable; coherent poison also fooled the critic.
- Decision: do not open validation and do not present v1 as a successful defense. Redesign Stage 4
  as anchor-then-challenge proposition checking with an explicit 23/38 feasibility gate.

## 2026-08-09 — Strict same-model A/B/C redesign started

- Reframed the primary evaluation per victim model: the same model must provide RAG, three-repeat
  closed-book judgments, routing, and proposition verification.
- Removed the three-model candidate panel and fixed Qwen evidence critic from the primary workflow.
- Added endpoint-only and all-top-k-evidence router variants that can select only an existing
  endpoint; this isolates routing from synthesis.
- Added targeted Stage C for every clean or attacked endpoint disagreement: a fresh same-model
  closed-book proposition check followed by same-model endpoint selection.
- The 318 cached clean-plus-1% source rows require 636 A/B router calls. All upstream RAG and
  closed-book outputs are reused, and validation remains unopened.

## 2026-08-09 — Strict same-model A/B/C design run completed

- Completed and audited 636/636 A/B router outputs, 136/136 proposition checks, and 136/136 final
  endpoint selectors; full replay produced 908/908 cache hits and immutable output reuses.
- Llama endpoint-only reached 34/44 at 1%, above Llama RAG (29/44) and closed-book (31/44), but its
  39/60 clean accuracy missed the clean gate.
- Targeted Stage C reached 35/44 at 1% and 43/60 clean for Llama. It beats both attacked endpoints
  and is one clean case below RAG, satisfying the practical design gate.
- GLM and Qwen did not pass. The Llama paired gain over closed-book is 6 wins versus 2 regressions
  (two-sided exact McNemar p=0.289), so this is exploratory and model-conditional.
- Fifteen disagreement routers omitted a concrete proposition and used an explicitly recorded
  generic claim-check fallback. Validation remains unopened.

## 2026-08-10 — Stage 4 controls, freeze, and validation completed

- Preregistered and ran a seven-call, rationale-firewalled two-proposition workflow plus an
  equal-call five-direct-answer control on Llama method-design disagreements. The proposition
  workflow reached 34/44 at 1% but only 38/60 clean, so it failed the frozen clean gate and was not
  tuned further.
- Selected the already completed two-call Stage C because it passed method-design, exceeded the
  seven-call direct control, and preserved clean accuracy. Froze its model, prompts, code, seeds,
  activation, action space, and split hashes in `configs/stage4_candidate_freeze.json`.
- Built and audited 476 validation packets, ran 68/68 frozen Llama routers, and ran 37/37 Stage C
  disagreement checks/selectors with zero failure before joining validation gold.
- At 1% validation, Stage C reached 23/28 versus poisoned RAG 21/28 and same-model closed-book
  16/28. The paired gain over closed-book was 7--0 (two-sided exact p=0.0156). Clean was 27/40
  versus RAG 28/40: one case, or 2.5 points, below RAG.
- Added a post-validation but outcome-untuned exact-budget generic-check ablation. It reached 21/28
  at 1% validation and 29/40 clean, revealing a real robustness/utility tradeoff from targeting:
  two attacked gains and two clean losses relative to generic checking.
- Decision: the result is sufficient for a narrow workshop claim that internal knowledge can help
  one same-model workflow under non-adaptive 1% poisoning. It is not model-general, not a certified
  defense, and not yet a locked-test result.

## 2026-08-10 — Frozen 0.1% extension completed

- Froze the 0.1% rate extension before outputs and ran the unchanged Stage C workflow for all three
  models on method-design. GLM reached 44/49 versus closed-book 42/49 and RAG 36/49; Llama reached
  40/44 versus RAG 39/44 and closed-book 31/44. Both passed the design gate. Qwen tied RAG at 37/45
  and failed clean utility, so it was not validated.
- One-shot validation did not reproduce a strict win: GLM Stage C tied closed-book at 28/33, and
  Llama Stage C reached 23/28 versus RAG 24/28. The negative result is retained; 0.1% is not used as
  a replacement headline setting.
- Audits passed 459 router rows and 161 Stage C outputs across design and validation with no
  identity, same-model, prompt-privacy, contract, or immutable-output failure.

## 2026-08-10 — Frozen 1% crossed attacker-victim diagnostic completed

- Reused all attacker-specific poison artifacts on the 61 claims eligible for all victims and
  completed the full 3×3 matrix: 549/549 rows, including 366 new off-diagonal victim endpoints,
  with zero runtime or audit failure.
- GLM poison was strongest: mean ASR 60.7% across victims. Qwen poison reached 46.4%; Llama poison
  reached only 18.0%. Fixed-victim accuracy changed by 25--27 cases when switching from GLM to
  Llama poison, with paired exact p-values below `1.5e-6` for every victim.
- GLM was the most robust victim averaged across attackers (67.8% accuracy), despite its weak
  same-model diagonal. Llama's strong diagonal was caused mainly by its weak poison generator;
  under GLM poison, Llama accuracy fell to 36.1%.
- Decision: attacker identity is a major confound. Future defense results must include all cells or
  a predeclared fixed/held-out attacker rather than selecting the weakest generator.

## 2026-08-10 — Frozen Stage C crossed-defense run completed

- Built and audited 849 attacker-hidden packets: 300 clean and all 549 crossed attack rows. The
  router completed 849/849 outputs and Stage C processed the expected 357/357 endpoint
  disagreements with zero final audit failure.
- The practical attacker-aggregated gate passed for GLM (157/183 Stage C versus 153 model-only and
  124 RAG) and Llama (127 versus 120 and 98). Qwen reached 143 versus model-only 144 and failed its
  clean budget, so the predeclared overall two-victim gate passes but not all three models.
- Claim-clustered 95% intervals for the Stage-C-minus-model-only delta include zero for every
  victim. Under the strongest GLM attacker, Stage C reaches 131/183 versus model-only 139/183; its
  positive aggregate result is driven mainly by the weak Llama attacker and slightly by Qwen.
- Recorded two non-semantic operational recoveries: a pre-call crossed-task adapter, and a
  versioned single-field typo repair added after 848 router outputs but before gold evaluation. A
  Qwen network timeout was recovered through idempotent cache replay.
- Decision: retain the result as workshop-level evidence that parametric knowledge can help two
  same-model pipelines across multiple non-adaptive generators, but do not claim strong-attacker
  or statistically confirmed model-general robustness. Next design should neutralize proposition
  framing and make the final selector safety-first before opening locked claims.

## 2026-08-10 — Neutral firewalled workflow completed; semantic guard isolated

- Froze a same-model four-call workflow before collection: claim-only neutral planning, supportive
  and skeptical retrieval-isolated checks, and a rationale-firewalled endpoint selector. Added an
  exact-call three-direct-assessment control and predeclared strongest-attacker and method-specific
  gates.
- Completed 1,532 maximum fresh calls with zero failure. The pre-label audit passed 186 plans, 372
  neutral checks, 558 direct controls, 416 unique selectors, and 714 row-level outputs without
  prompt leakage or provenance/contract failure.
- The literal frozen selector failed: 415/549 attacked versus closed-book 417 and direct control
  416. Only GLM passed the per-victim practical gate; GLM-attacker performance was 135/183 versus
  closed-book 139.
- Post-label diagnosis found a missing semantic validator. The frozen prompt allowed retrieval only
  under two-check convergence backed by direct factual support, yet 20/28 attacked retrieval
  requests violated the full condition; all 10 `Supported | Refuted` conflict selections were wrong.
- Enforcing the already-frozen necessary condition with no new LLM calls yields exploratory
  423/549 versus closed-book 417, direct control 416, and RAG 320. It accepts eight switches: seven
  rescues and one regression. GLM and Qwen pass the practical gate; strongest-GLM-attacker accuracy
  is 140/183 versus closed-book 139.
- Decision: treat the unconstrained run as the formal frozen result and the policy-enforced run as
  a transparent post-label implementation correction. Freeze the guard and require one untouched
  held-out confirmation before making a headline claim.

## 2026-08-10 — Locked Stage 5 confirmation authorized and frozen

- The user authorized opening the untouched 100-claim balanced binary locked split.
- Froze the exact strict semantic guard, four-call neutral workflow, exact-call direct control,
  three attackers, three victims, 1% rate, clean-correct intersection rule, gates, source hashes,
  and no-retuning stopping policy before any locked model output.
- Fixed workload before eligibility: 900 closed-book outputs and 300 clean RAG endpoints. The
  crossed matrix size is deliberately dynamic at nine times the jointly clean-correct claim count.
- Added separate locked namespaces and adapter/audit/evaluation scripts; development code and
  artifacts remain immutable.

## 2026-08-10 — Locked internal collection amendment 1

- Llama completed 300/300 valid internal outputs. Qwen completed 297/300; the three failures were
  the same claim under all seeds, and every original/two-retry response terminated for length
  without valid JSON. No held-out accuracy had been computed.
- Before continuing, recorded a one-retry increase for the internal contract only. It uses the
  unchanged format-repair function and model settings, retains every failed attempt, forbids
  malformed-output parsing or claim deletion, and does not change any decision rule or gate.

## 2026-08-10 — Locked internal collection amendment 2

- The additional Qwen format retry also terminated for length for claim 264 under seeds 11, 29,
  and 47. The raw internal audit therefore remains formally incomplete at 897/900 valid outputs.
- Before any successful locked RAG call or gold evaluation, recorded a deterministic fail-closed
  `Not Enough Evidence` endpoint. No malformed answer content is parsed, and the claim remains in
  primary scoring. The evaluator must also recompute every frozen gate after excluding all rows
  that use this one endpoint; a conclusion that depends on it is not accepted.

## 2026-08-10 — Locked clean-RAG amendment 3

- The first clean pass produced 298/300 endpoints before eligibility or accuracy evaluation. For
  Llama claim 228, all three answer attempts returned only one of ten requested entries; for claim
  383, valid calls reached the artifact boundary with a raw URL still present.
- Recorded two general conservative adapters: omitted answer indices become explicit null answers,
  and the declared URL firewall is applied recursively at final normalization. Neither adapter
  creates factual content, changes a model verdict, consults gold, or changes retrieval/attacks.
- A targeted cached replay located the URL edge case at an evidence truncation boundary ending in
  the bare prefix `https://`; masking now covers that zero-suffix prefix as well.

## 2026-08-10 — Locked Stage 5 amendment 4

- The first Stage 5 pass retained 770/780 row outputs before audit. One Qwen counter-check timed
  out and remains subject to ordinary idempotent replay. Separately, Qwen claim 264 exhausted all
  three attempts for both neutral checks and all three exact-control perspectives; all 15 outputs
  were repetitive, length-truncated, and invalid JSON.
- Before any held-out label join, predeclared a case-specific fail-closed resolution: both workflow
  variants copy the existing memory endpoint, invoke no selector, and retain every failed cache
  key. The rule cannot improve over model-only on the affected rows and is not allowed to absorb
  network/provider failures.
- The four affected rows remain in primary scoring. Amendment 2's mandatory sensitivity already
  excludes all Qwen claim-264 rows, so the confirmation conclusion must remain unchanged there.

## 2026-08-10 — Locked Stage 5 confirmation completed

- Both pre-label audits passed: 993 attacker-hidden inputs, 780/780 Stage 5 row outputs, zero
  unresolved failure, and no same-model, provenance, prompt-isolation, or contract-integrity
  violation. Gold was then joined exactly once under the frozen stopping policy.
- On 693 attacked rows, strict reached 554 correct (79.94%) versus poisoned RAG 396, same-model
  closed-book 561, and exact-call direct control 563. It therefore fails both the endpoint-win and
  method-specificity goals.
- GLM strict reached 198/231 attacked versus memory 195 and RAG 156, but clean was 84/100 versus
  clean RAG 88 and direct control was 200/231. Llama tied memory under attack and lost 17 clean
  points; Qwen lost ten attacked cases to memory and nine clean points to RAG. No victim passes.
- Under the strongest GLM attacker, strict was 181/231 versus memory 187. Excluding the four Qwen
  claim-264 rows leaves every gate false. The frozen workflow is a negative result and will not be
  tuned on the locked set.
- Decision: the current positive defense claim is rejected. Retain either a workshop-level
  characterization of the limits of endpoint-only parametric firewalls or begin a new method cycle
  with evidence-aware/cross-model information and a genuinely fresh confirmation set.

## 2026-08-10 — Frozen intermediate-rate endpoint scan completed

- Filled the gap between the prior 0.1% and 1% anchors with 0.25%, 0.5%, and 0.75% diagonal
  Fact2Fiction conditions. All 681/681 new attacked endpoints completed; the scoped 981-endpoint
  clean-plus-attack audit found no missing task, poison-material failure, or victim-prompt failure.
- Across the same 227 clean-correct victim/claim pairs, poisoned RAG moves from 182 correct at 0.1%
  to 177 at 0.25%, 151 at 0.5%, 132 at 0.75%, and 113 at 1%. Same-model closed-book remains 175;
  the three-model closed-book panel remains 192.
- The pooled RAG/model-only crossover is near 0.25%, but this hides model heterogeneity: GLM favors
  memory, Llama favors RAG through 1%, and Qwen is individually closest at 0.1%--0.25%.
- At 0.25%, the panel-plus-RAG oracle is 218/227 versus the panel's 192/227, so a multi-model blend
  has 26 possible RAG rescues but 41 panel-only cases it must protect.
- Decision: develop an evidence-aware LLM workflow jointly on 0.1% and 0.25%, use 0.5% as a
  transition stress test, and report internal-only as the appropriate baseline/default at stronger
  rates. Do not tune on a favorable rate and present the same claims as independent validation.

## 2026-08-11 — Endpoint-hidden passage-signal diagnostic completed

- Froze and collected same-model claim plans and passage maps for every cached endpoint
  disagreement on clean, 0.1%, 0.25%, and 0.5%. All 159 plans and 363 passage maps completed; the
  pre-label audit found zero scope, cache, prompt-reconstruction, contract, URL, model, condition,
  or origin leak failure.
- Recorded a 24-row pre-gold contract pilot. Seventeen outputs initially passed; six failures had
  complete passage assessments but omitted context from content clusters, and one long output
  omitted passage assessments. Amendment 1 relaxed cluster coverage only and added exact missing-ID
  format feedback. The replay completed 24/24 without changing semantic requirements.
- After the audit, gold-joined whole-system accounting showed a strict retrieval-default diagnostic
  at 184/227 for 0.1%, versus RAG 182 and same-model memory 175. The gain comes from only two claims.
  It ties RAG at 0.25% and is below memory by 24 cases at 0.5%.
- On 243 attacked exclusive disagreements, strict evidence direction aligns with RAG 48 times and
  is wrong in 41; it aligns with memory only four times. Claim-grouped structured probes improve
  2.5--3.3 accuracy points over a constant endpoint, but claim-bootstrap intervals broadly include
  zero.
- Decision: do not run a final arbiter over the original passage map alone. The next method cycle
  adds symmetric queries and leave-decisive-document-out counter-retrieval so the arbiter observes
  independent corroboration rather than rereading the same potentially fabricated assertion.

## 2026-08-11 — Endpoint-calibration and answerability diagnostics

- Reconstructed all 363 clean/low-rate endpoint disagreements and evaluated only inference-visible
  endpoint reliability fields with all rows for the same claim held in one fold. A pooled endpoint
  logistic probe reaches 80.4% on exclusive disagreements versus a 50.8% constant endpoint; its
  claim-bootstrap improvement interval is `[+14.2, +46.1]` points. This is post-label development,
  not a frozen learned defense.
- Identified a simpler model behavior: use the three-sample closed-book majority when it is binary,
  otherwise use RAG. The development cascade reaches 237/300 clean and 200/227, 200/227, 195/227
  at 0.1%, 0.25%, and 0.5%, beating both pooled endpoints at every attacked rate.
- Retrospective transfer to the previously opened locked artifacts shows the same answerability
  cascade at 576/693 attacked versus memory 561 and RAG 396, but only 241/300 clean versus RAG 260.
  A frozen shared calibrated router reaches 577/693 attacked and 248/300 clean. These locked numbers
  are explicitly retrospective and cannot be described as confirmation.
- Mechanistic conclusion: the useful internal signal is claim-level selective answerability, not
  unconditional model-only replacement and not closed-book subquestion extraction. Qwen's failure
  mode is overconfidence—it never abstains—while Llama's abstention behavior is highly selective.

## 2026-08-11 — Leave-original-out counter retrieval completed

- Froze a second retrieval view for all 363 endpoint disagreements. It reuses the ten original
  claim queries, excludes every original document ID and exact-text digest, selects the next five
  eligible documents per query, and deduplicates across queries without backfill.
- The offline retrieval audit passed 363/363 before map calls. The new view contains poison in
  0.114%, 0.112%, and 0.589% of passages at 0.1%, 0.25%, and 0.5%; only 2/82, 2/83, and 10/98 rows
  are exposed. The method never receives those private counts or origins.
- The same model produced all 363 endpoint-hidden evidence reports. Two first-pass provider read
  timeouts were recovered by idempotent replay; all 361 successful outputs were cache hits and only
  the missing two calls were issued. The final audit passed without scope, reconstruction, prompt,
  same-model, contract, or provenance failure.
- A typed development rule uses the answerability cascade by default and switches only when the
  second-view direction matches exactly one endpoint. It reaches 244/300 clean and 208/227,
  210/227, 202/227 at the three rates, versus RAG at 227, 182, 177, 151 and memory at 207, 175,
  175, 175. It beats both endpoints for GLM, Llama, and Qwen separately at all attacked rates.
- Across the 363 disagreements, the rule makes 34 corrections and two regressions relative to
  answerability. Only 14 claims switch; the claim-clustered 95% interval for its accuracy gain is
  `[+3.8, +14.1]` points. This is a selected development candidate and requires fresh claims.

## 2026-08-11 — Frozen corroboration controller and plus variants completed

- Before calls, froze and audited 363 same-model controller packets containing endpoint labels,
  closed-book reliability fields, limited RAG process statistics, and original/leave-original-out
  evidence summaries. Condition, rate, model, attacker, origin, URL, RAG prose, poison count, and
  gold were absent. All 363 calls and the final audit completed without failure.
- The free-form controller is negative: it reaches 241/300 clean and 201/227, 198/227, 189/227 at
  0.1%, 0.25%, and 0.5%, below the typed rule. A predeclared semantic guard reaches 238, 203, 203,
  199 and also remains worse. The LLM often preserves Qwen's confident wrong memory answer despite
  direct counter evidence and sometimes accepts uncorroborated original evidence for GLM.
- A claim-grouped endpoint-calibration fusion adds no value: it ties the typed method at 0.1% and
  0.5%, loses two cases at 0.25%, and loses one clean case.
- The cached three-family closed-book plus variant changes 11 rows, all correctly on development,
  and reaches 248/300 clean and 212/227, 211/227, 204/227. Those overrides represent only five
  distinct claims and require extra model families, so the plus remains secondary.
- Decision: freeze the typed same-model corroboration method for fresh confirmation; retain the
  free-form controller and endpoint fusion as negative ablations; do not add a third retrieval pass
  before generalization is tested. Exact results are in `docs/COUNTER_RETRIEVAL_RESULTS.md`.

## 2026-08-11 — Query-aligned trace feasibility passed

- Kept the selected corroboration candidate unchanged and froze an artifact-only audit of the 363
  existing endpoint disagreements before aggregate analysis.
- Distinguished top-k poison exposure from poison actually selected by a question answer. Only a
  selected passage enters the final RAG judge's evidence record.
- Across 263 attacked disagreements, RAG is wrong on 149 rows. Poison is selected on 136/149
  errors versus 28/114 correct rows, a 3.72-fold prevalence ratio. The result covers every victim
  and passes all frozen follow-up gates.
- This is localization, not causation: correct RAG traces can also select poison, especially at
  0.5%. Froze a two-repeat same-model replay of the exact ten RAG questions before issuing calls.

## 2026-08-11 — Query-aligned replay and fixed-context intervention completed

- Completed 318/318 same-model closed-book replays of the exact ten RAG questions: 159 unique
  victim/claim plans under two seeds. Questions and claim date were the only factual inputs.
- Completed 304/304 unique same-model semantic-comparison packets and expanded them to all 363
  endpoint-disagreement rows. No comparator saw passages, endpoint verdicts, rate, provenance, or
  gold. All renderer/parser amendments were recorded before provenance or label analysis.
- On 263 attacked disagreements, conflict-flagged RAG traces were wrong 97/129 times versus 52/134
  unflagged, a 1.94 risk ratio. Suspects contained actual poison on 89/129 flagged rows, but the
  signal was strongly model-dependent and nearly absent for Llama.
- Froze and completed 165 answer plus 165 verdict reruns after globally removing suspect document
  identities from the already retrieved groups. The intervention made zero new retrieval calls and
  did not backfill removed documents.
- Unconditional replacement is strongly negative. Requiring the verdict to change yields three
  gains and four regressions against the selected corroboration method. Clean-only removals account
  for all four regressions.
- Post-label error analysis selected a repeated-but-localized rule: at least two conflicts, no more
  than one conflict per three stable internal answers, and a changed rerun verdict. It yields three
  row-level gains and no regressions, projecting to 244/300 clean and 209/227, 211/227, and 203/227
  at 0.1%, 0.25%, and 0.5%.
- The gains arise from only two distinct claims, Llama gains nothing, and the claim-clustered 95%
  interval starts at zero. The rule is a fresh-confirmation candidate, not an adopted replacement;
  `low_rate_corroboration_candidate_v1` remains selected.

## 2026-08-12 — Fixed-context RAG stress test completed

- Froze a no-retrieval stress intervention over all 363 clean and low-rate same-model endpoint
  disagreements. Completed 1,007 named views over 925 unique victim-visible contexts: two disjoint,
  exhaustive assertion-cluster halves per row and 281 applicable dominant-cluster removals.
- Reused the original ten questions, RAG answer prompt, RAG verdict prompt, and victim model. No new
  retrieval or backfill occurred. The subset contexts remained poisoned whenever they retained a
  poison document.
- Recorded one pre-analysis operational amendment for a GLM null answer with an orphan rank. The
  adapter removed only the invalid rank and performed no factual repair. Final stress coverage is
  925/925 unique contexts and 1,007/1,007 named views.
- Froze and completed 227 matched-control plus 227 stress-informed same-model selectors over
  opposing binary endpoints. Exact caching yielded 407 unique provider calls and 1,034,308
  referenced tokens.
- The selector result is negative. Projected selected/matched-control/stress correct counts are
  244/242/241 clean, 208/203/204 at 0.1%, 210/204/199 at 0.25%, and 202/199/191 at 0.5%. On 173
  attacked binary disagreements the three methods score 154, 140, and 128.
- Post-label nested claim-grouped calibration shows that structural stress signals improve champion
  error-ranking AUC from 0.625 to 0.737, but produce no attacked-set gain. Adding the LLM's stress
  assessment gives one attacked gain and one regression.
- Decision: retain `low_rate_corroboration_candidate_v1`; treat fixed-context stress arbitration as
  a negative ablation. Next investigate a precommitted two-scale method in which claim-level sealed
  memory is combined with an environment-level RAG--memory drift alarm, rather than another
  unconstrained per-claim judge. Full results are in `docs/RAG_CLUSTER_STRESS_RESULTS.md`.

## 2026-08-12 — Environment-conditioned corroboration completed

- Added a gold-free, model-specific environment statistic: among claims with a binary three-call
  internal majority, compare the RAG/internal disagreement count with a clean Beta-binomial
  posterior predictive reference. The detector never receives rate, attacker, provenance,
  retrieved poison exposure, or correctness.
- A first frozen binary alarm was too coarse at 0.5% and removed two correct GLM corroboration
  decisions. Before collecting 0.75%/1% counter reports, recorded a three-tier evidence policy:
  loose corroboration when normal, only direct unopposed corroboration under warning, and no
  retrieval override under critical drift. Before collecting 4%/8% reports, recorded an unchanged
  high-rate extension and its matched always-blend ablation.
- Completed and audited 540 new original-view reports and 540 leave-original-out reports, with zero
  failure. The two source runs reference 834 unique cached calls; the two counter runs reference
  540 calls. Total accepted-record usage is 4,710,780 tokens.
- The full development curve scores 208, 210, 202, 197, 191, 179, and 182 of 227 at 0.1%, 0.25%,
  0.5%, 0.75%, 1%, 4%, and 8%. It beats both raw endpoints at every rate, but is one below the best
  simple ablations at 1% and four below memory-first at 4%.
- At 4%, the proposed gate prevents 23 always-blend errors and introduces none. At 8%, it prevents
  55 and introduces none; all three victims enter critical mode and the memory-first policy scores
  182 versus model-only 175 and poisoned RAG 51. The counter view itself contains 33.6% and 65.2%
  poison documents at 4% and 8%, so repeated retrieval is not assumed clean.
- On the disjoint but previously opened 1% crossed matrix, the frozen detector raises no clean
  alarm and alarms in all six GLM/Qwen-attacker cells, but none of the three weaker Llama-attacker
  cells. This supports observed-environment conditioning rather than a hard nominal-rate switch.
- Decision: retain the low-rate corroboration rule as the claim-scale component and adopt the
  environment statistic as a complementary authority gate for the next fresh experiment. The
  complete result is development-selected, batch-delayed, and vulnerable to sparse/adaptive
  attacks; it is not independent confirmation. See `docs/ENVIRONMENT_CONDITIONED_RESULTS.md`.
