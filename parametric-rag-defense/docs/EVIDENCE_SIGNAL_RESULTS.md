# Passage-level evidence-signal results

Status: complete development diagnostic. These 100 claims are available for method tuning and are
not independent validation.

## What was run

The experiment collected endpoint-hidden passage reports wherever a model's RAG verdict differed
from its own three-repeat closed-book majority. The same model performed every role. Reports saw
the claim, a neutral claim-only decomposition, the retrieval questions, and every exact-unique
top-k excerpt, but not either endpoint, model identity, attack condition, rank, origin, URL, or
gold label.

- 159 claim-only plans and 363 passage reports completed.
- Coverage was 100 clean, 82 at 0.1%, 83 at 0.25%, and 98 at 0.5%.
- All 363 reports passed their structured contract; the final pre-label audit found zero leakage,
  provenance, cache, or coverage failure.
- The 522 accepted cache records reference 1,752,120 tokens. This is accepted-record accounting,
  not an estimate of incremental billing because compatible claim plans were reused from cache.
- The 24-row contract pilot and its pre-gold format-only amendment are preserved separately.

The primary machine-readable result is `artifacts/evaluation/evidence_signal_v1.json`. The complete
inference boundary and collection commands are in `docs/EVIDENCE_SIGNAL_PROTOCOL.md`.

## Whole-system diagnostic outcomes

The numbers below pass endpoint agreements through unchanged and apply a fixed evidence-direction
diagnostic only to endpoint disagreements. They are not a tuned final defense.

| Condition | Rows | RAG | Closed book | Strict, default RAG | Strict, default closed book |
|---|---:|---:|---:|---:|---:|
| Clean | 300 | 227 (75.7%) | 207 (69.0%) | 232 (77.3%) | 228 (76.0%) |
| 0.1% | 227 | 182 (80.2%) | 175 (77.1%) | 184 (81.1%) | 168 (74.0%) |
| 0.25% | 227 | 177 (78.0%) | 175 (77.1%) | 177 (78.0%) | 166 (73.1%) |
| 0.5% | 227 | 151 (66.5%) | 175 (77.1%) | 151 (66.5%) | 157 (69.2%) |

The 0.1% result technically exceeds both endpoints by two cases. It is not yet a defensible positive
method result:

- the two beneficial switches are only two claims, one for GLM and one for Llama;
- Llama's beneficial claim repeats at 0.25%, so the across-rate pattern is not independent;
- the GLM explanation contains a numerical inconsistency while arriving at the correct direction;
- no gain remains at 0.25%, and the rule is far below closed book at 0.5%.

Per-model behavior is heterogeneous. A retrieval-default rule adds one Llama case on clean, 0.1%,
and 0.25%, but has almost no coverage. On clean data, a memory-default rule helps GLM and Qwen
substantially. Under attack, the same action becomes unsafe for both models. Selecting a different
rule after inspecting each model/rate cell would be post-hoc cherry-picking, not a deployable
workflow.

## What the passage reports actually learned

On the 243 attacked rows where exactly one endpoint was correct, the strict passage direction had
the following alignment:

| Strict passage direction | Rows | Correct alignment | Wrong alignment |
|---|---:|---:|---:|
| Agreed with RAG | 48 | 7 | 41 |
| Agreed with closed book | 4 | 3 | 1 |
| No decisive direction | 191 | — | — |

This is the central result. When a poisoned passage is fluent, direct, and internally consistent,
the mapper correctly recognizes what that passage says and frequently reinforces the poisoned RAG
verdict. It has no independent basis for deciding whether the passage is authentic.

One representative failure is claim 32. A single injected excerpt falsely states that the New York
Post endorsed Joe Biden and explicitly rejected Trump's re-election. The GLM passage mapper calls
that excerpt direct refutation with no quality concern, changing a correct closed-book answer to the
wrong RAG answer. The mapper is doing passage interpretation, not source verification.

The structured features contain at most a weak exploratory signal. With all conditions for the same
claim held in one cross-validation fold:

| Features | Attacked endpoint-exclusive rows | Accuracy | Stronger constant | Difference | Claim-bootstrap 95% interval |
|---|---:|---:|---:|---:|---:|
| Passage structure only | 243 | 55.6% | 53.1% | +2.5 points | [-11.1, +15.7] |
| Structure + endpoint alignment | 243 | 56.4% | 53.1% | +3.3 points | [-10.6, +17.1] |

The intervals include zero by a wide margin. These probes justify further investigation of evidence
structure, but not an endpoint-selection claim.

## Decision

Do not spend calls on a final LLM arbiter that receives only the two endpoints and this passage map.
That would preserve the identified information bottleneck: another model can reason more carefully
over the same text but still cannot authenticate its decisive assertion.

The next signal experiment must add evidence not contained in the original poisoned top-k:

1. build symmetric claim-only queries for evidence supporting and refuting the claim;
2. run counter-retrieval after excluding the original decisive document or assertion cluster;
3. measure whether the conclusion survives across distinct retrieved documents and query views;
4. give an LLM workflow both endpoint verdicts, the original passage map, and the corroboration
   report, with `escalate` as an explicit action;
5. compare against a cost-matched direct answer, the current passage map alone, and simple
   structure-only selectors.

This keeps the broad paper question intact—when can internal knowledge protect RAG?—while replacing
the unsupported premise that an LLM can detect poisoning merely by rereading poisoned prose.

## Reproduction artifacts

- Freeze: `configs/evidence_signal_v1_freeze.json`
- Pre-gold contract amendment: `configs/evidence_signal_v1_amendment_1.json`
- Prompt: `prompts/evidence_passage_map_v1.md`
- Collection: `scripts/run_evidence_signal.py`
- Pre-label audit: `scripts/check_evidence_signal.py`
- Evaluation: `scripts/summarize_evidence_signal.py`
- Progress: `artifacts/runs/progress/evidence_signal_v1.json`
- Run audit: `artifacts/runs/evidence_signal/evidence_signal_v1/audit.json`
- Evaluation JSON: `artifacts/evaluation/evidence_signal_v1.json`
