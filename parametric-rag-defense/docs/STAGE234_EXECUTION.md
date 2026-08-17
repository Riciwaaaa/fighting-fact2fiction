# Stage 2--4 execution and artifact boundaries

This document is the operational map for the claim-level defense experiment. The scientific plan
is in `RESEARCH_PLAN.md`; this file states which artifacts are safe to show to a model and how to
resume each experiment without silently regenerating prior calls.

## Tracked control plane

```text
configs/splits/stage234_development.json  # frozen 60-design / 40-validation claim groups
configs/stage234_workflow.json            # stage inputs, roles, success gates, freeze policy
prompts/stage3_*_v1.md                     # exact critic and arbiter prompts
prompts/stage3_*_v1.md.sha256              # prompt locks
prompts/aligned_*_v1.md                    # strict same-model A/B/C prompts
prompts/aligned_*_v1.md.sha256             # aligned prompt locks
experiments/registry.json                  # lifecycle/dependency registry
docs/EXPERIMENT_LOG.md                     # concise human milestone log
```

The split unit is a claim. Every victim, internal model, seed, clean condition, and attack strength
for one claim stays in the same partition. Method selection may use only the 60-claim
`method_design` partition. The 40-claim `development_validation` partition is opened once after the
Stage 3 prompt and model roles are frozen. The original 100-claim locked test remains unopened.

## Generated data plane

Generated payloads are Git-ignored and resumable:

```text
artifacts/cache/llm/entries/                 # immutable paid-call cache
artifacts/runs/progress/                     # current snapshots + append-only event ledgers
artifacts/runs/stage1/development/rag/
  stage1_rag_v1.2/
    endpoints/                               # normalized endpoint judgments
    private_traces/                          # retrieval origin, condition, and call receipts
    poison_corpora/                          # attack texts and embeddings
    manifests/                               # batch completion/failure receipts
artifacts/runs/stage2/stage2_signal_v1/
  packets/                                   # sanitized, identity-masked inference packets
  private_index.json                         # claim/model/condition routing; never prompt-visible
  manifest.json                              # aggregate packet counts and index digest
artifacts/runs/stage3/stage3_claim_arbiter_v1/
  outputs/                                   # immutable critic/arbiter judgments
  private_manifest.json                      # evaluation routing; never prompt-visible
artifacts/runs/stage3/stage3_same_model_ab_v1/
  packets/{endpoint_only,evidence_aware}/    # one victim's RAG + its own memory only
  outputs/                                   # immutable endpoint-selector judgments
  private_manifest.json                      # evaluation routing; never prompt-visible
artifacts/runs/stage4/stage4_same_model_c_v1/
  outputs/                                   # closed-book proposition check + final selector
  private_manifest.json                      # evaluation routing; never prompt-visible
artifacts/evaluation/                        # gold-joined summaries; never an inference input
```

Every Stage 3 call serializes only a Stage 2 packet's `visible` object. Packet `provenance`, private
indexes, gold labels, attack conditions, model identities, raw URLs, and source-origin markers are
excluded. An automated validator fails on forbidden inference-visible keys, URLs, or `clean:N` /
`poison:N` identifiers.

## Progress visibility

Show every durable experiment snapshot:

```bash
.venv/bin/python scripts/show_experiment_progress.py
```

Each experiment has a current JSON snapshot and an append-only JSONL history under
`artifacts/runs/progress/`. `docs/EXPERIMENT_LOG.md` records the higher-level decisions, including
failed or superseded runs. Generated manifests retain individual failures rather than silently
changing denominators.

## Execution sequence

After Stage 1 v1.2 passes its independent audit:

```bash
# Freeze/reproduce the claim-grouped development split.
.venv/bin/python scripts/make_stage234_split.py

# Build all four attack levels plus clean packets for method_design only.
PYTHONPATH=src .venv/bin/python scripts/build_stage2_packets.py
PYTHONPATH=src .venv/bin/python scripts/check_stage2_packets.py

# Join gold only in this offline signal characterization.
PYTHONPATH=src .venv/bin/python scripts/summarize_stage2_signal.py

# First run a small contract/integration smoke test; its calls remain cached.
PYTHONPATH=src .venv/bin/python scripts/run_stage3_claim_arbiter.py --claims 0

# Run the full 60-claim clean + 1% pilot and evaluate it.
PYTHONPATH=src .venv/bin/python scripts/run_stage3_claim_arbiter.py --workers 6
PYTHONPATH=src .venv/bin/python scripts/summarize_stage3_claim_arbiter.py
```

Stage 4 is not run merely because Stage 3 emits propositions. It starts only after inspecting the
Stage 3 design results and freezes a selective escalation rule. An `escalate` Stage 3 output still
contains a fallback verdict, so Stage 3 can be evaluated independently and Stage 4 rescue/regression
can be measured without denominator changes.

The redesigned strict same-model workflow is documented in `docs/ALIGNED_SAME_MODEL_PROTOCOL.md`.
Its executable sequence is:

```bash
# A/B: exactly the same model provides RAG, closed-book judgments, and routing.
.venv/bin/python scripts/run_aligned_router.py --workers 6
.venv/bin/python scripts/check_aligned_router.py
.venv/bin/python scripts/summarize_aligned_router.py

# C: choose the frozen A/B variant, then check only endpoint disagreements.
.venv/bin/python scripts/run_aligned_verification.py --variant <endpoint_only|evidence_aware> --workers 6
.venv/bin/python scripts/check_aligned_verification.py
.venv/bin/python scripts/summarize_aligned_verification.py
```
