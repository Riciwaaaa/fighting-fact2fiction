# Parametric knowledge as a defense against poisoned RAG

Status: execution plan, version 8; environment-conditioned corroboration selected for fresh confirmation
Dates: 2026-08-08--2026-08-12

The active candidate has changed. On the current 100 development claims, leave-original-out
retrieval plus a typed same-model evidence report and an answerability fallback reaches 208/227,
210/227, and 202/227 at 0.1%, 0.25%, and 0.5% poisoning. The corresponding poisoned-RAG counts are
182, 177, and 151; same-model closed book is 175 at every rate. The method beats both endpoints for
GLM, Llama, and Qwen individually at all three rates. A free-form same-model LLM controller over
the same information is worse, so it is a negative ablation rather than the proposed aggregator.
The exact result, limitations, and fresh-confirmation protocol are in
`docs/COUNTER_RETRIEVAL_RESULTS.md`; the selected candidate is frozen in
`configs/low_rate_corroboration_candidate_v1.json`.

The completed two-scale extension now supplies the broader method. The defense uses clean-calibrated
RAG/internal disagreement over a model-specific batch to decide whether leave-original-out
retrieval may loosely corroborate an endpoint, must provide direct unopposed evidence, or may not
override answerable internal memory at all. It never receives the nominal poisoning rate. Across
the 227 development rows it beats both raw endpoints from 0.1% through 8%; at 8% it reaches 182
correct versus model-only 175, poisoned RAG 51, and always blending 127. It is not uniformly best
among internal ablations: memory-first reaches 192 versus 191 at 1% and 183 versus 179 at 4%.
Therefore the full method is a fresh-confirmation candidate, not a confirmed result. See
`docs/ENVIRONMENT_CONDITIONED_RESULTS.md` and
`configs/environment_conditioned_candidate_v1.json`.

The corrected Stage 1 v1.2 produced 900 cached model-only outputs, 300 clean RAG endpoints, and 908
attacked endpoints at four poisoning levels. Stage 2 built 732 sanitized design packets. Stage 3 v1
then completed 318 critics and 636 arbiters, but reached only 74.6% at 1% poisoning versus 84.8% for
the strongest model-only endpoint. Thus its primary success gate failed. The 100-claim locked test
was subsequently opened once under a separate frozen confirmation. See
`docs/STAGE1_RAG_V12_RESULTS.md`,
`docs/STAGE2_SIGNAL_RESULTS.md`, and `docs/STAGE3_CLAIM_ARBITER_RESULTS.md`.

The final locked confirmation is negative. Across 693 attacked rows, the strict neutral-firewall
workflow reaches 554 correct versus same-model closed-book at 561, exact-call direct deliberation
at 563, and poisoned RAG at 396. No victim satisfies the combined attacked-win and clean-utility
gate, and every criterion remains false after the mandatory Qwen-264 exclusion. The current method
must not be tuned on the locked split. See `docs/LOCKED_CONFIRMATION_RESULTS.md`.

Stage 3 v1 aggregated victims and supplied every arbiter with three models' memory candidates, so it
does not test the primary deployment configuration cleanly. The active A/B/C redesign evaluates
each model separately with the same model producing RAG, closed-book judgments, routing, and
targeted proposition verification. See `docs/ALIGNED_SAME_MODEL_PROTOCOL.md`.

The completed redesign reaches 35/44 for Llama at 1%, above its 31/44 closed-book and 29/44 RAG
endpoints, with 43/60 clean accuracy versus clean RAG's 44/60. After prompt/code/seed hashes were
frozen, one-shot development-validation reaches 23/28 at 1%, above closed-book at 16/28 and RAG at
21/28; the paired gain over closed-book is 7--0 (exact p=0.0156). Clean is 27/40 versus RAG at
28/40. GLM and Qwen do not pass the design gate. See `docs/ALIGNED_SAME_MODEL_RESULTS.md` and
`docs/STAGE4_FINAL_RESULTS.md`.

## 1. Research objective

This project asks a broad question:

> Can the internal knowledge of large language models defend retrieval-augmented systems against
> corpus poisoning, and under what conditions does it help or fail?

The empirical target is stronger than detecting conflicts. The proposed workflow must improve the
final task outcome:

> For at least one pre-specified model, after claim-level arbitration (Stage 3), and again after
> targeted proposition verification (Stage 4), the defended system should outperform both that
> same model's poisoned-RAG and closed-book endpoints on held-out attacked claims, while retaining
> most of the stronger clean endpoint's accuracy.

This is a target and preregistered success condition, not a result we assume in advance.

## 2. Motivation from the existing experiment

The previous project has 100 claims with both model-only and poisoned-RAG endpoint outputs. They
contain complementary errors:

| Outcome | Claims |
|---|---:|
| Model-only and poisoned RAG both correct | 49 |
| Only model-only correct | 32 |
| Only poisoned RAG correct | 10 |
| Both wrong | 9 |

The endpoint accuracies are 81% for model-only and 59% for poisoned RAG. An oracle that selects the
correct endpoint reaches 91/100 = 91%. Thus, there is empirical headroom for arbitration. On the 96
claims that also completed the old fusion stage, that fusion reached only 67.7%, showing that
indiscriminate evidence pooling does not exploit the headroom.

Among the 42 endpoint disagreements, “always choose model-only” is already 32/42 = 76.2% accurate.
Stage 3 must beat that disagreement-routing baseline. It must recover RAG-only successes more often
than it abandons correct model-only answers.

The old 96-claim run is exploratory evidence only. It has a selected binary sample and contaminated
URL-bearing confidence prompts. It may be used for pipeline development and legacy comparisons, but
not as the locked confirmatory test.

## 3. Main research questions

- **RQ1 — Existence of signal:** Do retrieval-free model judgments contain a reliable signal that
  a RAG verdict has been altered by poisoning?
- **RQ2 — End-task utility:** Can an LLM arbitration workflow use that signal to outperform both
  poisoned RAG and model-only on final verdict accuracy and macro-F1?
- **RQ3 — Granularity:** Does targeted inspection of decisive subquestions improve over claim-level
  arbitration alone?
- **RQ4 — Model independence:** Do cross-model or multi-model internal judgments improve robustness
  over a victim model checking itself?
- **RQ5 — Limits:** How do recall confidence, claim age/popularity, label, attack rate, and adaptive
  poisoning affect the value of internal knowledge?

## 4. Hypotheses and success conditions

### 4.1 Primary hypotheses

- **H1:** Closed-book/RAG disagreement is enriched for poisoned RAG errors, but disagreement alone
  is insufficient for routing.
- **H2:** For at least one model, a frozen same-model LLM router using independently generated RAG
  and closed-book endpoint outputs outperforms both of that model's endpoints under poisoning.
- **H3:** Targeted subquestion escalation further improves the Stage 3 workflow, particularly when
  claim-level internal confidence is low or models disagree.
- **H4:** Cross-model internal agreement can add value beyond same-model self-checking after the
  primary same-model result is established and inference budget is controlled.
- **H5:** Benefits decrease on recent and long-tail facts for which parametric recall is absent or
  stale.

### 4.2 Confirmatory success gates

On the locked primary test at 1% poisoning:

1. Stage 3 accuracy or macro-F1 must exceed both the same model's poisoned-RAG and closed-book
   endpoints; results are never pooled across victim models for this gate.
2. Stage 4 must also exceed both endpoints and should exceed Stage 3; if it does not, subquestion
   escalation is reported as a negative ablation rather than part of the proposed method.
3. The paired 95% confidence interval for the primary improvement over the stronger endpoint must
   exclude zero, or the preregistered paired test must pass after Holm correction.
4. Clean performance should be within 2 percentage points of the stronger same-model clean
   endpoint. A larger loss must be
   presented as a robustness/utility tradeoff, not a clean-preserving defense.
5. The LLM workflow must beat “always choose model-only” on cases where model-only and poisoned RAG
   disagree.
6. Gains must survive URL/metadata masking and a cost-matched repeated-call control. Cross-model
   configurations are secondary extensions rather than requirements for the same-model claim.

If Stage 3/4 do not beat both endpoints, the work pivots to a characterization paper and does not
claim an effective defense.

Llama 3.1 70B is the primary confirmatory model because the frozen design endpoints show the
largest 1% same-model selection headroom (7/44 cases above its stronger endpoint). Qwen and GLM are
secondary replications. This priority is fixed before inspecting any aligned-router outcome or
opening development-validation.

## 5. Threat model

- The attacker can add a specified fraction of documents to the retrieval corpus and can tailor
  poison to the victim fact-checker's decomposition, as in Fact2Fiction.
- The attacker cannot modify model weights or intercept retrieval-free calls.
- The main evaluation uses a defense-unaware attacker. A smaller adaptive evaluation targets common
  internal beliefs and low-recall facts.
- The defender has no clean corpus, planted-document label, synthetic URL marker, or trusted-domain
  oracle at inference time.
- The primary goal is robust final verdicts, not perfect poisoned-document classification.

## 6. System overview

All model calls are immutable, content-addressed artifacts. Later stages consume cached outputs and
never silently regenerate them. Gold labels and attack labels are excluded from every inference
prompt and are joined only during evaluation.

### Active low-rate method revision (2026-08-11)

The endpoint-hidden passage experiment found that passage semantics alone are not an adequate
poison signal. On attacked endpoint-exclusive disagreements, a strict original-passage direction
agreed with RAG 48 times and was wrong in 41. The completed counter-retrieval experiment therefore
excludes every original document and exact text, retrieves a second view using the cached claim
queries, and asks the same model for an endpoint-hidden evidence report.

The selected primary workflow is now:

1. use same-model closed-book when its three-sample majority is binary, otherwise use RAG;
2. override that fallback only when the leave-original-out report has a directional label matching
   exactly one endpoint;
3. do not use the free-form controller or a third retrieval pass in the primary method;
4. report the three-family closed-book panel only as a costlier plus variant.

The LLM still performs the semantic evidence interpretation. A typed controller boundary prevents
it from ignoring direct corroboration or trusting persuasive original evidence without an
independent basis. This change supersedes the earlier assumption below that Stage 3 must itself be
a free-form LLM decision. The current 100 claims remain method-development data; fresh claims are
required next. Exact results are in `docs/COUNTER_RETRIEVAL_RESULTS.md`.

### Environment-conditioned extension (2026-08-12)

The low-rate method should not be applied unconditionally. At 4% and 8%, its second retrieval view
contains poison in 33.6% and 65.2% of retrieved documents and always blending falls to 156/227 and
127/227. The complete candidate therefore adds a gold-free environment scale:

1. estimate a model-specific clean distribution for disagreement between answerable internal
   majorities and RAG;
2. over a shared inference window, measure whether observed disagreement is plausible under that
   clean distribution;
3. use loose independent corroboration under normal behavior, require direct unopposed evidence
   under warning behavior, and prohibit retrieval-based overrides under severe behavior;
4. in severe mode, use the internal binary majority and fall back to RAG only when the three
   internal calls are not answerable.

This is not a nominal-rate decision tree: rate, attacker, provenance, poison exposure, and gold are
forbidden inputs. On a previously opened cross-claim 1% diagnostic, the detector alarms for all
six GLM/Qwen-generated attack environments but none of the three substantially weaker
Llama-generated environments, while raising no clean alarm. The main limitations are delayed
batch detection, vulnerability to sparse/adaptive attacks, and the lack of untouched confirmation.
The exact policy, full rate curve, calls, and caveats are in
`docs/ENVIRONMENT_CONDITIONED_RESULTS.md`.

### Stage 0 — Protocol and data freeze

1. Define development and locked test claim IDs before method tuning.
2. Follow Fact2Fiction's first eligibility filter for the primary experiment: retain only
   `Supported` and `Refuted` claims. Keep four-label behavior as a named exploratory diagnostic.
3. Use 100 balanced binary development claims and 100 disjoint balanced binary locked claims.
   Preserve the previous 20 non-binary development claims and their cached outputs as a historical
   conflict/NEI diagnostic, never as part of the primary denominator.
4. Deduplicate the normalized claim text/date visible to endpoints across development, locked, and
   diagnostic partitions before any model-specific eligibility filtering.
5. Record dataset version, split seed, attack rate, attack seed, code commit, model identifiers, and
   provider metadata in every run manifest.
6. Mask URLs and condition-specific metadata from all LLM inputs.

### Stage 1 — Cache independent endpoint judgments

For each claim and condition, cache outputs before any endpoint sees the other endpoint's answer.

#### 1A. RAG endpoint

Cache:

- final verdict and confidence;
- final justification;
- generated questions/subclaims;
- retrieved evidence after removing attack-revealing metadata;
- adopted answers and dropped/NONE questions;
- retrieval ranks and scores where available;
- cost, latency, model revision, decoding settings, and random seed.

#### 1B. Internal endpoint

Each retrieval-free model returns:

- a four-label-capable final verdict (scored against binary gold in the primary experiment, so an
  abstaining/non-binary prediction counts as incorrect rather than being silently remapped);
- confidence;
- `knowledge_basis = direct_recall | inference | insufficient_knowledge`;
- concise rationale;
- decisive propositions supporting the verdict;
- premise concerns;
- optional repeated samples for consistency.

Run at least:

- the victim model without retrieval;
- one different-family model without retrieval;
- a second cross-model reasoner if budget permits.

#### Cache requirements

- Cache keys include the exact messages, provider, model, prompt ID/version, decoding parameters,
  response format, seed, and cache schema version.
- Cache records never contain API keys or authorization headers.
- Writes are atomic and schema-validated. Existing but corrupt outputs cause a hard failure rather
  than a skip.
- A per-key lock prevents parallel workers from issuing duplicate paid calls.
- Parsed output, raw response, usage, latency, provider response/model ID, and provenance are stored.
- Legacy outputs may be imported with an explicit `legacy` provenance tag. They cannot be relabeled
  as outputs from the new prompt or used as locked test results.

Stage 1 is executed once per model/configuration. Stages 2–5 reuse the exact cached records.

### Stage 2 — Characterize the internal-knowledge signal

Without changing any verdict, measure:

- final-verdict agreement and disagreement;
- correctness conditional on internal confidence and knowledge basis;
- same-model versus cross-model agreement;
- ensemble consistency;
- claim-level and decisive-proposition conflict;
- performance on long-tail/recent versus familiar claims;
- the empirical oracle ceiling between each pair of endpoints.

This stage establishes whether useful complementarity exists and identifies features that can be
shown to the Stage 3 LLM. It is diagnostic, not the defense.

### Stage 3 — Strict same-model endpoint routing

Stage 3 is an LLM workflow, not a fixed decision tree.

For each model independently, the router receives:

- the claim and claim date;
- RAG verdict, concise rationale, and summarized evidence;
- only that same model's three cached closed-book verdicts, rationales, knowledge bases,
  confidence, and consistency;
- either no excerpts (endpoint-only A) or every cached source-neutral top-k excerpt (evidence-aware
  B);
- no gold label, attack label, raw URL, system name, or condition marker.

The arbiter must:

1. identify the decisive disagreement;
2. assess which endpoint has stronger epistemic support;
3. explicitly distinguish direct recall, inference, and absence of knowledge;
4. avoid treating non-recall as proof that a retrieved assertion is false;
5. select the retrieval or memory endpoint and optionally request proposition verification.

The router cannot synthesize a third verdict. Its evaluated output is copied exactly from its
selected endpoint, separating routing ability from additional claim answering.

The prompt and examples are tuned only on development data and frozen before test. Arbitration
outputs are cached like all other model calls.

The same model supplies the RAG endpoint, memory endpoint, and router. Independent and multi-model
arbiters are secondary ablations only. Stage 3 passes only if it beats both same-model standalone
endpoints on held-out attacked data.

### Stage 4 — Targeted same-model proposition verification

Stage 4 is invoked whenever the same model's two endpoint verdicts disagree, in both clean and
attacked conditions. This condition-blind activation avoids using arbiter confidence as a gate.

The escalation workflow:

1. The same-model router extracts one neutral proposition that could resolve the endpoint conflict.
2. A fresh closed-book call to that model checks the proposition without seeing endpoint or
   retrieved content and may reject a false premise.
3. A fresh final call to the same model receives the endpoints, router record, and independent
   proposition check, then selects one existing endpoint.

All intermediate calls are cached. Stage 4 must be compared with:

- Stage 3 alone;
- the endpoint-only versus evidence-aware A/B input;
- checking every victim-generated subquestion as a later ablation;
- one-model versus multi-model proposition answering as a secondary extension;
- cost-matched additional claim-level deliberation.

Stage 4 belongs in the proposed method only if it still beats both endpoints and adds value over
Stage 3 commensurate with its cost.

### Stage 5 — Locked evaluation

Run the frozen workflow on the locked test and join gold/attack metadata only after all predictions
are complete.

## 7. Multi-model design and controls

Multi-model reasoning is treated as a scientific variable, not an unqualified add-on.

| Configuration | Question answered |
|---|---|
| Victim model checks itself without retrieval | Is same-model parametric knowledge useful? |
| Different model supplies the internal answer | Does cross-model independence help? |
| Two internal models plus an arbiter | Does parametric consensus improve routing? |
| Same models used as a model-only ensemble | Is retrieval contributing anything? |
| Stronger model used directly as model-only and RAG | Is a gain merely raw capability? |
| Cost-matched repeated calls to one model | Is a gain merely extra inference budget? |
| Arbiter/model role swaps | Does the result depend on one privileged model? |

Models, versions, providers, temperatures, seeds, and reasoning settings must be fully recorded.
The main sweep uses an explicit non-thinking profile for switchable reasoning models so every call
reliably emits its structured endpoint judgment within a controlled budget. A preregistered subset
uses native thinking with a larger budget as a sensitivity analysis. If that profile is stronger,
it is included as an additional standalone model-only baseline. Hidden reasoning is neither stored
nor exposed to later stages.

## 8. Data and experiment matrix

### 8.1 Main data

- 200 AVeriTeC claims passing Fact2Fiction's binary-label filter: 100 development and 100 locked,
  each balanced between `Supported` and `Refuted` and mutually disjoint.
- Apply Fact2Fiction's second, victim-specific eligibility filter only after clean RAG outputs are
  cached: a claim enters that victim's attacked paired analysis only if its clean verdict is
  correct. Report both the pre-filter coverage and each victim's resulting eligible denominator.
- 50–100 temporal or long-tail claims to probe weak/outdated internal knowledge.
- The previous 96 binary examples and 20-claim conflict/NEI diagnostic are
  exploratory/development data only.

### 8.2 Poisoning conditions

Poisoning strength has two distinct definitions and they must not be conflated:

- **PoisonedRAG axis:** `N = 0, 1, ..., 10` malicious documents per target question, with retrieval
  `k = 5`. The original paper evaluates `N=1` through `10`, uses `N=5` by default, and observes
  saturation once `N >= k`. `N=0` is our clean condition.
- **Fact2Fiction axis:** corpus fractions 0%, 0.1%, 0.5%, 1%, 2%, 4%, 8%, 12%, and 16%. Its core
  table uses 1%, 2%, 4%, and 8%; its extended strength curve includes 0.1%, 0.5%, 12%, and 16%.
- Record the realized injected-document count and final-corpus poison fraction per claim. The
  reference implementation's integer conversion can map distinct nominal rates to the same count,
  especially at 0.1%; nominal rate alone is not an adequate audit variable.
- Do not directly compare the numerical x-values of PoisonedRAG's per-query `N` axis with
  Fact2Fiction's per-claim corpus-fraction axis. Report separate curves and compare defended systems
  against their endpoints within each condition.
- Primary confirmatory conditions include 1% Fact2Fiction and PoisonedRAG `N=5`; the complete
  curves characterize robustness rather than selecting a favorable attack strength.
- Use three attack seeds for primary locked conditions and one seed for the full strength sweep.
- Add one smaller adaptive attack targeting model misconceptions or missing knowledge.

References: [PoisonedRAG](https://www.usenix.org/conference/usenixsecurity25/presentation/zou-poisonedrag)
and [Fact2Fiction](https://trustworthycomp.github.io/Fact2Fiction/).

### 8.3 Stage 1 model coverage

The starting NVIDIA-hosted model matrix is:

- `nvcf/meta/llama-3.1-70b-instruct`;
- `nvidia/qwen/qwen3.5-35b-a3b`;
- `nvidia/qwen/qwen3-5-397b-a17b` on the NVIDIA development endpoint;
- `nvidia/zai-org/glm-5.2`.

Each enabled model is used as an internal endpoint, RAG victim, and (in controlled role-swap
experiments) arbiter. Retrieval-free outputs are generated once per claim/model/decoding repeat and
reused across every attack strength. RAG outputs are separately keyed by victim model, attack
family, strength, and attack seed.

### 8.4 Minimum viable workshop matrix

If cost is constrained:

- 100 development and 100 locked test claims;
- 0%, 1%, and 8% poisoning;
- one victim, two internal models, and one independent arbiter;
- three decoding repeats for internal/arbiter calls;
- claim-level Stage 3 on all cases;
- Stage 4 on endpoint disagreements and low-confidence cases only.

## 9. Baselines

Required:

1. clean RAG reference;
2. poisoned RAG;
3. each individual model-only endpoint;
4. model-only ensemble;
5. always choose model-only when endpoints disagree;
6. simple majority/LLM vote without evidence roles;
7. skeptical prompting;
8. one strong robust-RAG baseline such as RobustRAG or a faithful TrustRAG adaptation;
9. Stage 3 claim-level arbitration;
10. Stage 4 targeted escalation;
11. attack-label oracle as an analysis-only upper bound.

The old symmetric fusion method is retained as a negative ablation, not a competitive baseline.

## 10. Metrics and statistical analysis

### Primary end-task metrics

- attacked accuracy and macro-F1;
- clean accuracy and macro-F1;
- attack success rate relative to clean RAG;
- defense recovery and regression rates;
- accuracy restricted to endpoint disagreements;
- selective risk/coverage where the workflow abstains.

### Signal and workflow metrics

- endpoint oracle ceiling;
- arbitration accuracy on model-only/RAG disagreements;
- RAG-only successes recovered;
- correct model-only answers sacrificed;
- Stage 4 rescue and regression counts relative to Stage 3;
- calibration by confidence and knowledge basis;
- cost, latency, and model calls per claim.

### Statistical unit and tests

- Claims, not subquestions, are the independent unit.
- Use paired claim bootstrap intervals stratified by label and attack seed.
- Use paired McNemar tests for correctness with Holm correction over predefined primary comparisons.
- Use claim-cluster bootstrap intervals for proposition/subquestion analyses.
- Report every missing or failed output; never silently change the denominator.

## 11. Leakage and reproducibility requirements

- No raw URLs are shown to any model unless URL reasoning is a separately declared ablation.
- Remove `/created`, `is_fake`, attack condition, dataset split, gold label, and source-side names from
  inference records.
- Randomize endpoint order in arbiter prompts and measure position bias.
- Store the prompt text/hash and code commit with each call.
- Use atomic artifacts, strict schemas, immutable manifests, and completeness checks.
- Keep cache/artifact payloads out of Git by default; commit manifests, schemas, prompts, aggregate
  results, and small licensed examples.
- Never store credentials in the repository or cache.

## 12. Execution sequence

1. Initialize the new repository and implement the Stage 1 cache and schemas.
2. Define the development/test split and model-role configuration.
3. Import legacy outputs as development-only artifacts with explicit lineage.
4. Freeze the four-label-capable internal-answer prompt and its exact byte-level digest.
5. Run and cache Stage 1 endpoint outputs.
6. Produce Stage 2 complementarity and calibration report.
7. Develop and freeze the Stage 3 LLM arbiter on development data.
8. Test the Stage 3 success gate on locked data.
9. Develop and freeze Stage 4 targeted escalation without modifying Stage 3 test outputs.
10. Run the complete baseline, multi-model, granularity, and cost-control matrix.
11. Perform statistics, human audit, and adaptive/long-tail stress tests.
12. Write the paper according to the observed result: successful defense only if the preregistered
    gates pass; otherwise a boundary/negative study.

## 13. Initial repository structure

```text
parametric-rag-defense/
  README.md
  RESEARCH_PLAN.md
  pyproject.toml
  configs/
  prompts/
  schemas/
  src/parametric_rag_defense/
  scripts/
  tests/
  artifacts/            # generated, ignored except manifests/examples
```
