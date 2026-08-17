# Locked confirmation protocol

Status: completed under the frozen protocol; the confirmation gate failed. The user authorized
opening the original 100-claim binary locked split on 2026-08-10. Final metrics and interpretation
are in `docs/LOCKED_CONFIRMATION_RESULTS.md`.

Execution amendment 1: during internal collection, Qwen entered a length-terminated generation
loop on one claim for all three seeds after the original two format retries. Before any held-out
accuracy evaluation, the maximum internal format retries was increased from two to three for all
models. No malformed answer is parsed, no claim is dropped, and all attempts remain cached. The
machine-readable timing, scope, and constraints are in
`configs/stage5_locked_confirmation_amendment_1.json`.

Execution amendment 2: the additional Qwen retry also failed for that same claim under all three
seeds. Before any successful locked RAG call or accuracy evaluation, the endpoint was assigned a
fail-closed `Not Enough Evidence` abstention without parsing any malformed text. The claim remains
in primary scoring, and a mandatory second evaluation excludes every row that uses this one
endpoint. Conclusions must be invariant to that sensitivity analysis. Exact values, hashes, and
constraints are in `configs/stage5_locked_confirmation_amendment_2.json`.

Execution amendment 3: after 298/300 clean RAG endpoints succeeded, one Llama answer batch had
valid entries but omitted nine requested indices, and one otherwise-valid endpoint retained a raw
URL at normalization. Before eligibility or any accuracy evaluation, missing entries were mapped
to explicit null answers (never invented content), and URL masking was enforced recursively at the
normalization boundary. Both are model-agnostic, fail-closed contract policies. Exact timing,
rules, and implementation hashes are in `configs/stage5_locked_confirmation_amendment_3.json`.

Execution amendment 4: the first Stage 5 pass cached 770/780 row outputs. A transient counter-check
timeout remains an ordinary idempotent replay, while Qwen claim 264 produced 15 length-truncated,
contract-invalid responses across both checks and all three cost-control perspectives. Before any
gold evaluation, that predeclared case was assigned the workflow's memory fallback for both
variants; no selector is called and no malformed text is parsed. The four rows remain in primary
scoring and are also covered by amendment 2's mandatory Qwen-264 exclusion sensitivity. Exact
scope and constraints are in `configs/stage5_locked_confirmation_amendment_4.json`.

## Question

Does the exact Stage 5 strict neutral-firewall workflow reproduce its development advantage over
both poisoned RAG and same-model closed-book under a complete 3×3 non-adaptive 1% attacker-victim
matrix, while preserving clean accuracy for at least two victim models?

The strict workflow is unchanged: it accepts an LLM retrieval choice only when both independent
checks converge on the retrieval label, both identify their knowledge basis as direct recall, and
both provide at least one decisive proposition. Otherwise it selects the closed-book endpoint.

## Execution order

1. Collect and audit 900 three-repeat closed-book outputs.
2. Extract and index the official AVeriTeC resources for the locked claims, then collect 300 clean
   RAG endpoints and mechanically compute Fact2Fiction clean-correct eligibility.
3. Intersect eligibility across all three victims; generate each attacker's poison material and run
   every attacker-victim pairing on that common claim set at exactly 1%.
4. Build same-model, attacker-hidden endpoint packets and audit all endpoint/call provenance.
5. Run both the neutral workflow and its exact-call direct-deliberation control only on endpoint
   disagreements. Cache every plan, assessment, selector, and row descriptor.
6. Audit Stage 5 completeness, same-model identity, and prompt isolation.
7. Join locked labels once, compute the frozen gates, and stop without tuning.

The exact rules, models, seeds, hashes, and stopping policy are in
`configs/stage5_locked_confirmation_freeze.json`.

## Artifact layout

- Internal endpoints: `artifacts/runs/stage1/locked_test/internal_endpoint/`
- Clean RAG: `artifacts/runs/stage1/locked_test/rag/stage1_locked_confirm_v1/`
- Crossed 1% RAG: `artifacts/runs/stage1/locked_test/rag/stage1_locked_crossed_1pct_v1/`
- Attacker-hidden inputs: `artifacts/runs/stage3/stage3_locked_neutral_inputs_v1/`
- Stage 5 outputs: `artifacts/runs/stage5/stage5_locked_neutral_firewall_v1/`
- Runtime ledgers: `artifacts/runs/progress/*locked*`
- Final evaluation: `artifacts/evaluation/stage5_locked_neutral_firewall_v1.json`

## Commands

```bash
PYTHONPATH=src .venv/bin/python scripts/prepare_stage1_kb.py \
  --split locked_test --device cuda:0 --batch-size 32
PYTHONPATH=src .venv/bin/python scripts/run_stage1_internal.py \
  --split locked_test --allow-locked-test --workers 6 --contract-retries 3
PYTHONPATH=src .venv/bin/python scripts/audit_stage1_internal.py --split locked_test
PYTHONPATH=src:scripts .venv/bin/python scripts/run_locked_clean_rag.py \
  --allow-locked-test --workers 6
PYTHONPATH=src:scripts .venv/bin/python scripts/run_locked_crossed_rag.py \
  --allow-locked-test --workers 6
PYTHONPATH=src:scripts .venv/bin/python scripts/build_locked_neutral_inputs.py \
  --allow-locked-test
PYTHONPATH=src:scripts .venv/bin/python scripts/check_locked_confirmation_inputs.py
PYTHONPATH=src .venv/bin/python scripts/run_neutral_firewall.py \
  --router-root artifacts/runs/stage3/stage3_locked_neutral_inputs_v1 \
  --experiment-id stage5_locked_neutral_firewall_v1 --workers 6 \
  --fail-closed-case-keys c89017674fc158eda01c9eea9cb1217b7521e882e0774c17dc45873f27c034f4
PYTHONPATH=src .venv/bin/python scripts/check_neutral_firewall.py \
  --run-root artifacts/runs/stage5/stage5_locked_neutral_firewall_v1
PYTHONPATH=src:scripts .venv/bin/python scripts/summarize_locked_neutral_firewall.py
```
