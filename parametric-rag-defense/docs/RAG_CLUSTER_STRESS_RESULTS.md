# Fixed-context RAG stress test: development results

Status: complete negative method-development experiment. The selected
`low_rate_corroboration_candidate_v1` remains unchanged.

## Question and information boundary

This experiment tested a stricter version of the internal-knowledge story. The model first made
three independent, closed-book judgments of the complete claim. Those judgments were sealed before
retrieval was shown. When the closed-book majority and RAG disagreed, RAG was rerun on controlled
subsets of its **existing** retrieved context:

- two deterministic, disjoint, exhaustive halves of anonymous assertion clusters; and
- when possible, one view with the largest direct cluster supporting the original RAG verdict
  removed.

The reruns did not retrieve or backfill anything. They therefore retained poison whenever poison
was present in the selected subset. This makes the comparison fair to the attacked RAG setting,
but it also means that a stable verdict is not necessarily an authentic verdict.

The same victim model then chose among the RAG label, the closed-book label, and the already
selected corroboration label. A matched control saw the identical packet without stress outcomes.
Neither selector saw raw passages, factual cluster summaries, condition, nominal rate, model ID,
poison provenance, attacker identity, or gold.

## Completed scope and accounting

- Source: all 363 clean, 0.1%, 0.25%, and 0.5% same-model endpoint disagreements.
- Stress views: 1,007 named views, comprising 363 complementary half pairs and 281 applicable
  dominant-cluster removals.
- Exact prompt deduplication: 925 unique RAG contexts.
- Stress inference: 925 answer calls plus 925 verdict calls before format repair.
- Selector scope: the 227 disagreements whose endpoints were opposing binary labels.
- Selector inference: 227 matched-control plus 227 full outputs; exact prompt caching reduced these
  to 407 unique provider calls.
- Selector usage: 928,725 prompt tokens and 105,583 completion tokens, 1,034,308 total.
- Final coverage: complete, with no retrieval or backfill calls in the stress intervention and no
  failed rows.

One GLM answer repeatedly returned an orphan rank with a null answer. Before any stress accuracy or
provenance analysis, a narrow amendment was recorded that discards only that rank when status and
answer are both null. The standard parser then accepted the output. No factual text was repaired.

## Primary result

The free-form selector is worse than the selected typed corroboration method.

| Condition | Rows | Selected corroboration | Matched control | Stress-informed selector |
|---|---:|---:|---:|---:|
| Clean | 300 | **244 (81.3%)** | 242 (80.7%) | 241 (80.3%) |
| 0.1% | 227 | **208 (91.6%)** | 203 (89.4%) | 204 (89.9%) |
| 0.25% | 227 | **210 (92.5%)** | 204 (89.9%) | 199 (87.7%) |
| 0.5% | 227 | **202 (89.0%)** | 199 (87.7%) | 191 (84.1%) |

On the 173 attacked opposing-binary disagreements, selected corroboration is correct on 154,
matched deliberation on 140, and the stress-informed selector on 128. Relative to the selected
method, the full selector makes six corrections but introduces 32 errors. Its claim-clustered 95%
accuracy-difference interval is `[-24.9, -6.6]` percentage points. The matched control makes no
correction and introduces 14 errors.

The action distribution explains the damage. The matched control mostly keeps the champion (208
of 227 rows) and otherwise always requests memory. Adding stress outcomes makes the model much more
active: it keeps the champion 114 times, requests memory 73 times, and requests RAG 40 times. The
additional interventions are not reliable.

## Why it fails

The causal perturbation answers “does this context subset change the RAG computation?” It does not
answer “is the underlying assertion authentic?” Two failure modes are unavoidable:

1. Poison can survive in both complementary halves or be repeated across anonymous assertion
   units, so robustness can be robustness of the attack.
2. A decisive clean fact can be concentrated in one assertion cluster, so sensitivity to removing
   that cluster is not evidence that it was poisoned.

The same-model arbiter overinterprets both patterns. It treats persistence as truth and
concentrated influence as suspicion. Meanwhile, some Qwen internal answers are three-for-three,
high-confidence, `direct_recall` judgments and are still wrong. Confidence and self-reported recall
therefore cannot authenticate memory either.

This reinforces an earlier result: LLMs are useful for extracting typed semantic observations,
but an unconstrained LLM should not be expected to assign the correct causal meaning to those
observations.

## Conservative rescue diagnostic

After seeing the negative selector result, an explicitly post-label diagnostic estimated only one
quantity: whether switching away from the selected champion would correct a champion error. It used
nested cross-validation grouped by claim and omitted attack rate, condition, model identity,
provenance, and gold from the features.

| Feature family | OOF AUC | Activations | Gains | Regressions | Attacked net |
|---|---:|---:|---:|---:|---:|
| Existing observable signals | 0.625 | 3 | 0 | 3 | -3 |
| Existing + structural stress signals | **0.737** | 1 | 1 | 0 | 0 |
| Existing + stress + LLM assessment | 0.719 | 3 | 2 | 1 | 0 |

The one structural-stress correction occurs on clean data. On attacked rows, the conservative
stress model makes no change; including the arbiter assessment produces one gain and one regression.
Thus stress structure improves error ranking but does not yield a demonstrated attacked-set gain
over the already strong selected method. These results are method-development evidence only.

## Decision and next hypothesis

Do not add fixed-context stress arbitration to the primary method. The selected same-model method
remains:

1. three retrieval-isolated full-claim judgments;
2. an answerability fallback;
3. leave-original-out retrieval using the original claim-generated questions; and
4. a typed override only when that independent evidence report points to exactly one endpoint.

The next worthwhile hypothesis operates at two scales rather than adding another per-claim judge:

- **Claim scale:** use repeated closed-book agreement as a sealed parametric-memory signal and
  independent corroboration as the only retrieval override.
- **Environment scale:** calibrate, on a clean reference stream, how often answerable internal
  judgments disagree with RAG. A sustained excess disagreement is a retrieval-drift alarm. The
  alarm is derived from observed outputs, not a supplied attack rate.
- **Routing:** in the normal regime, retain the selected corroboration method; in the drift regime,
  stop allowing uncorroborated RAG to override answerable memory; if memory is unanswerable, abstain
  or use an explicitly reported fallback.

The cached rate curve supports feasibility but not yet a method claim. On the same eligible claims,
answerable-memory disagreement rises from clean to 8% as follows:

| Model | Clean | 0.1% | 0.25% | 0.5% | 0.75% | 1% | 4% | 8% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GLM 5.2 | 9.1% | 27.3% | 29.9% | 39.0% | 46.8% | 55.8% | 66.2% | 76.6% |
| Llama 3.1 70B | 0.0% | 12.8% | 10.6% | 19.1% | 23.4% | 25.5% | 40.4% | 46.8% |
| Qwen 3.5 35B-A3B | 20.5% | 34.2% | 34.2% | 39.7% | 43.8% | 52.1% | 61.6% | 71.2% |

This table is retrospective and uses condition-sized batches; it must not be presented as a tested
online detector. The next experiment must freeze the clean calibration window, sequential alarm,
minimum batch size, response policy, and clean false-alarm budget before evaluating attack
conditions. It should also test mixed-rate and nonstationary streams so the environment assumption
is explicit.

## Reproduction artifacts

- Frozen stress protocol: `configs/rag_cluster_stress_v1.json`
- Operational amendment: `configs/rag_cluster_stress_v1_amendment_1.json`
- Stress implementation: `src/parametric_rag_defense/rag_stress.py`
- Stress collection: `scripts/run_rag_cluster_stress.py`
- Stress run: `artifacts/runs/rag_stress/rag_cluster_stress_v1/`
- Frozen selectors: `configs/rag_stress_arbiter_v1.json`
- Selector implementation: `src/parametric_rag_defense/rag_stress_arbiter.py`
- Selector collection: `scripts/run_rag_stress_arbiter.py`
- Selector evaluation: `scripts/summarize_rag_stress_arbiter.py`
- Selector JSON: `artifacts/evaluation/rag_stress_arbiter_v1.json`
- Post-label rescue diagnostic: `scripts/diagnose_rag_stress_rescue.py`
- Rescue JSON: `artifacts/evaluation/rag_stress_rescue_oof_v1.json`
