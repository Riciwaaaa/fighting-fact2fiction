# Strict same-model A/B/C protocol

Status: method-design A/B/C complete; method frozen and evaluated once on development-validation;
Llama meets the attacked-performance criterion and the original locked test remains unopened

## Primary question

For each model (M), can a workflow using (M) for the RAG endpoint, the closed-book endpoint, and
all routing/verifying calls outperform both standalone endpoints under Fact2Fiction poisoning?
Results are evaluated separately for each model. Cross-model aggregation and multi-model memory are
not primary results for this experiment.

## Cached inputs and scope

- Method-selection partition: the frozen 60-claim `method_design` partition.
- Initial conditions: clean and `fact2fiction_p0.01`.
- Models: Llama 3.1 70B, Qwen 3.5 35B-A3B, and GLM 5.2.
- Source rows: 318 = 180 clean model/claim pairs plus 138 eligible attacked pairs.
- Stage 1 RAG and three-repeat closed-book judgments are reused exactly; neither endpoint is rerun.
- The 40-claim `development_validation` partition was opened once after the Stage C freeze. The
  original locked test remains unopened.

## A/B — exact same-model routing

Both variants show the router exactly one RAG endpoint and that same model's three cached
closed-book judgments. The router must select an existing endpoint; its prediction is copied from
that endpoint, so routing is not confounded with synthesizing a new answer.

- **A / `endpoint_only`:** claim/date, RAG verdict/confidence/rationale/coverage, and the same
  model's closed-book repeat distribution and rationales. No retrieved excerpt is shown.
- **B / `evidence_aware`:** the same fields plus every cached normalized top-k excerpt for every
  RAG question. Evidence identifiers are source-neutral, and URLs and origin metadata remain
  unavailable.

The A/B contrast diagnoses whether evidence access supplies a useful conflict signal or instead
amplifies coherent poison. It does not compare different models or give the router privileged
attack metadata.

For every model and condition, evaluation reports RAG, same-model closed-book, router, endpoint
oracle, disagreement accuracy, RAG-only recoveries, memory-only sacrifices, and the exact paired
outcomes. The initial success gate is:

1. at 1% poisoning, router accuracy is strictly greater than both same-model endpoints; and
2. on clean data, router accuracy is no more than two percentage points below the stronger
   same-model endpoint.

Llama 3.1 70B is the primary model for A/B variant selection because its cached 1% endpoint oracle
has the largest absolute headroom over its stronger endpoint (7/44 cases). Qwen and GLM are
secondary replications. Among variants satisfying Llama's clean gate, Stage C uses the variant with
higher Llama 1% accuracy; an exact tie selects `endpoint_only` because it is cheaper and exposes
less potentially poisoned content. If neither variant satisfies the clean gate, Stage C still uses
the lower-clean-loss variant as a diagnostic; a clean-loss tie is resolved by higher 1% accuracy
and then by `endpoint_only`. Such a diagnostic cannot pass the full success gate unless Stage C
itself repairs the clean loss.

## C — targeted same-model proposition verification

After A/B selects an input variant on `method_design`, Stage C is invoked only when that model's RAG
and closed-book verdicts disagree.

1. The router names one neutral pivotal proposition and a provisional endpoint.
2. A fresh closed-book call to the same model sees only the original claim/date and pivotal
   proposition. It does not see either endpoint or retrieved evidence.
3. A fresh final call to the same model sees the endpoints, router record, and proposition check,
   then selects an existing endpoint. It cannot synthesize a third verdict.

Stage C runs on both clean and attacked disagreements so activation never reveals the condition.
Its contribution is evaluated as paired gains and regressions relative to both the A/B router and
the same-model closed-book endpoint.

## Poisoning-rate feasibility

The endpoint oracle bounds what endpoint selection alone can achieve. At 1%, recoverable cases
above the stronger endpoint are 3/49 for GLM, 3/45 for Qwen, and 7/44 for Llama. At 0.1%, cached
headroom is larger and the stronger endpoint is not always closed-book. The lower rate is therefore
a preregistered follow-up if the frozen A/B/C workflow cannot demonstrate a positive same-model
result at 1%; it is not used to alter prompts after inspecting validation data.

## Artifact layout

```text
artifacts/runs/stage3/stage3_same_model_ab_v1/
  packets/{endpoint_only,evidence_aware}/   # immutable inference-visible packets
  outputs/                                  # immutable router outputs
  private_manifest.json                     # model/condition routing; never prompt-visible
artifacts/runs/stage4/stage4_same_model_c_v1/
  outputs/                                  # proposition check + final selection records
  private_manifest.json
artifacts/runs/progress/                     # current snapshots and append-only JSONL events
artifacts/evaluation/                        # offline gold-joined summaries only
```

Prompt caches are content addressed. Audits verify same-model request identity, output identity,
contract replay, uniqueness/completeness, and absence of URLs, source origins, attack conditions,
or gold markers in all inference messages.
