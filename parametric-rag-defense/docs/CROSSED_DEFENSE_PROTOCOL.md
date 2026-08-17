# Frozen attack-generalization protocol for Stage C

This protocol was frozen before producing any router, proposition-check, or selector output for an
off-diagonal attacker-victim pair. It applies the already selected Stage C workflow unchanged to
the complete 3×3 Fact2Fiction 1% matrix.

## Inference scope

- Three RAG victims and three poison generators, with 61 common eligible claims in every cell.
- One hundred clean claims per victim for the clean-utility measurement.
- RAG, three-repeat closed-book, router, proposition checker, and selector all use the victim
  model. The attacker model generates poison only and is never exposed to the workflow.
- Endpoint agreement copies the common verdict. Endpoint disagreement activates one isolated
  proposition check and one endpoint-only selector.
- Prompts, decoding, activation, and output space are byte-identical to the frozen 1% Stage C
  workflow.

Private condition identifiers distinguish attacker cells in manifests. They, attacker identities,
model identities, source origins, attack metadata, and gold labels must not appear in model
messages. All clean and crossed endpoints are copied byte-for-byte into a dedicated combined
namespace so the frozen runner can resolve immutable task keys without changing its code.

## Evaluation gate

For each victim, aggregate the three equally sized attacker cells. Stage C must be strictly more
accurate than both same-model RAG and same-model closed-book over the resulting 183 rows. On the
100 clean claims, it may lose at most two percentage points from the stronger endpoint. The overall
model-general gate requires at least two victims to pass.

All nine cells and the strongest GLM-attacker cells are mandatory secondary results. Because three
attacks share each claim, aggregate uncertainty uses a 10,000-sample claim-cluster bootstrap rather
than treating 183 rows as independent.

## Interpretation

This experiment tests whether the existing workflow generalizes across poison generators. The
complete development set has already informed earlier diagnostics, so the result remains
development evidence. It cannot replace a later frozen evaluation on the unopened locked claims.

## Recorded execution deviations

The exact deviations are machine-recorded in `configs/crossed_defense_freeze.json` and retained in
the result interpretation. A first v1 launch stopped before any provider request because crossed
tasks used `victim_model_id` while the unchanged runner required `model_id`; a content-addressed v2
adapter fixed only that derived schema. After 848 router outputs and before reading gold or
aggregate results, one GLM response exhausted its format retries by misspelling
`decisive_conflict`. Router contract v1.1 therefore permits exactly one missing/extra field-key
pair only when its edit distance is at most two; it does not alter field values. One later Qwen
checker request timed out and was recovered through an idempotent cache replay. Prompts, visible
packets, decoding, model roles, activation, and endpoint decisions were otherwise unchanged.
