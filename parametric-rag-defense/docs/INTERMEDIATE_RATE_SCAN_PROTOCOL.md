# Intermediate-rate endpoint scan

Status: protocol frozen before collection; 681/681 new endpoint outputs are now complete and
audited. Results are in `docs/INTERMEDIATE_RATE_SCAN_RESULTS.md`.

## Question

The completed scan leaves a large gap between 0.1% and 1% Fact2Fiction poisoning. At 0.1%, RAG
and same-model closed-book accuracy are close; at 1%, RAG is much worse. This scan locates the
transition before designing or tuning a new evidence-aware blend.

This is development analysis. These 100 claims may be used for method tuning, but no performance
measured on them will be described as independent validation.

## Frozen scope

- Development split: 100 balanced binary claims.
- Fact2Fiction clean-correct filter: 82 GLM, 72 Llama, and 73 Qwen pairs; 227 total.
- Victim/attacker pairing: diagonal, using the same model's existing attack material.
- New nominal corpus fractions: 0.25%, 0.5%, and 0.75%.
- Expected new endpoints: 681.
- Attack seed: 101.
- Pipeline and victim prompts: unchanged v1.2 metadata-neutral InFact-style pipeline.
- Poison documents: nested prefixes of the existing 8% corpus, preserving the original blueprint
  order and embeddings.

The full machine-readable freeze is `configs/stage1_intermediate_rate_scan_freeze.json`.

## Commands

Run or resume collection:

```bash
.venv/bin/python scripts/run_stage1_rag_scan.py \
  --phase poison \
  --tier development_intermediate_sweep \
  --artifact-label intermediate_rate_scan_v1 \
  --experiment-id stage1_intermediate_rate_scan_v1 \
  --workers 6
```

Audit the scoped outputs and their referenced cache entries:

```bash
.venv/bin/python scripts/check_stage1_rag_scan.py \
  --tier development_intermediate_sweep \
  --allow-out-of-scope \
  --output artifacts/runs/stage1/development/rag/stage1_rag_v1.2/intermediate_rate_scan_v1_audit.json
```

Summarize endpoint complementarity without new model calls:

```bash
.venv/bin/python scripts/summarize_stage1_rag_scan.py \
  --scan artifacts/evaluation/stage1_rag_v1.2_intermediate_rate_scan_v1.json \
  --output artifacts/evaluation/stage1_rag_v1.2_intermediate_rate_complementarity_v1.json
```

Combine these results with the frozen 0.1%, 1%, 4%, and 8% anchors:

```bash
.venv/bin/python scripts/summarize_stage1_rag_scan.py \
  --scan artifacts/evaluation/stage1_rag_v1.2_initial_scan.json \
  --scan artifacts/evaluation/stage1_rag_v1.2_intermediate_rate_scan_v1.json \
  --output artifacts/evaluation/stage1_rag_v1.2_combined_rate_curve_v1.json
```

## Required reporting

For every model and rate, report RAG accuracy, same-model closed-book accuracy, three-model
closed-book accuracy, endpoint outcome counts, mean injected documents, realized corpus fraction,
and retrieved-poison fraction. The final interpretation must retain 0.1% and 1% as anchors and
must not select a single rate only because a later blend performs well there.
