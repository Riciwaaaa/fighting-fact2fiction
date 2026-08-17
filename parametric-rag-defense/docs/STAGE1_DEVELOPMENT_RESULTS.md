# Stage 1 development results: internal endpoint

Date: 2026-08-08

Scope: 100 unique development claims, 50 Supported and 50 Refuted, three decoding seeds per claim

These are development diagnostics, not locked-test or poisoning-defense results. They establish the
model-only baselines and cross-model complementarity before collecting matched clean and attacked
RAG endpoints. Gold labels were joined only after every prediction was cached.

## Data and coverage

- The split follows Fact2Fiction's first filter: only Supported/Refuted gold labels are candidates.
- All normalized claim/date prompts are unique within and across the 100-claim development,
  100-claim locked, and 20-claim historical diagnostic partitions.
- Three NVIDIA production models each completed 300/300 final outputs: 900 final outputs total.
- Provider-call failures: 0. Final contract failures: 0. Every final response stopped normally.
- Qwen produced three malformed first attempts. Three distinct format-repair calls succeeded; all
  invalid originals and repaired responses remain linked in the manifest and counted in cost.
- Qwen 3.5 397B-A17B remains unavailable because the supplied production credential is not accepted
  by NVIDIA's separate development endpoint.

The split originally contained repeated AVeriTeC records: one four-ID duplicate group in
development, one duplicate pair in locked, and two cross-split overlaps. They were discovered by an
endpoint-visible prompt audit, removed deterministically without consulting model correctness, and
replaced with label-matched unused claims. The pre-deduplication split and all superseded run
manifests remain archived.

## Model-only performance

Each endpoint prediction is the deterministic majority of its three cached samples. Binary
macro-F1 averages Supported and Refuted; a non-binary prediction remains an error for its gold
class rather than being remapped.

| Model | Accuracy | Binary macro-F1 | Three-seed unanimity | Mean reported confidence |
|---|---:|---:|---:|---:|
| Llama 3.1 70B | 54% | 67.5% | 100% | 0.589 |
| Qwen 3.5 35B-A3B | 73% | 72.0% | 94% | 0.942 |
| GLM 5.2 | 80% | 82.5% | 77% | 0.852 |

| Model | Supported accuracy (n=50) | Refuted accuracy (n=50) | Majority prediction counts |
|---|---:|---:|---|
| Llama 3.1 70B | 52% | 56% | 28 Supported, 32 Refuted, 40 NEI |
| Qwen 3.5 35B-A3B | 54% | 92% | 31 Supported, 69 Refuted |
| GLM 5.2 | 78% | 82% | 45 Supported, 49 Refuted, 4 Conflict, 2 NEI |

The models have substantially different behavior. Llama abstains on 40% of claims and reports
`insufficient_knowledge` in 116/300 samples. Qwen never abstains, is strongly biased toward
Refuted, and reports very high confidence. GLM is the strongest and most label-balanced individual
endpoint. Self-reported confidence is therefore not comparable across model families without
calibration.

## Cross-model signal

| Diagnostic | Result |
|---|---:|
| Three-model majority accuracy | 85% |
| Three-model majority binary macro-F1 | 85.8% |
| Any-model oracle accuracy | 89% |
| Claims where all three endpoint majorities agree | 44% |

Pairwise disagreement remains directional but nontrivial:

- Llama vs Qwen: 52 disagreements; only Llama correct on 10 and only Qwen correct on 29.
- Llama vs GLM: 46 disagreements; only Llama correct on 5 and only GLM correct on 31.
- Qwen vs GLM: 23 disagreements; only Qwen correct on 7 and only GLM correct on 14.

The simple three-model ensemble is five points above the strongest individual endpoint, while the
oracle leaves another four points of diagnostic headroom. This supports multi-model internal
knowledge as a baseline and possible arbitration feature. It does not yet establish that internal
knowledge detects poisoning or improves on RAG under attack.

## Cost and artifact audit

| Model | Final outputs | Total attempts | Total tokens | Median latency | p95 latency |
|---|---:|---:|---:|---:|---:|
| Llama 3.1 70B | 300 | 300 | 175,436 | 11.73 s | 31.00 s |
| Qwen 3.5 35B-A3B | 300 | 303 | 229,037 | 11.61 s | 29.75 s |
| GLM 5.2 | 300 | 300 | 193,539 | 9.84 s | 30.66 s |

Latency sums are not wall-clock runtime because four requests were executed concurrently. Token
counts include the three Qwen format repairs. NVIDIA endpoint usage in this run did not expose a
currency charge, so the report records tokens rather than inventing a dollar estimate.

The authoritative raw/parsed cache, active and historical manifests, run logs, audit ledger, and
gold-joined summary are documented in `docs/ARTIFACT_INVENTORY.md`. Revalidate without provider
calls using:

```bash
PYTHONPATH=src python3 scripts/check_stage1_internal.py
PYTHONPATH=src python3 scripts/audit_stage1_internal.py
PYTHONPATH=src python3 scripts/summarize_stage1_internal.py \
  --output artifacts/evaluation/stage1_internal_development.json
```

## Interpretation and next gate

The internal signal is strong enough to justify proceeding: GLM is a credible model-only baseline,
and multi-model majority reaches 85%. It also raises the bar. A defended poisoned-RAG workflow must
beat the strongest standalone model-only endpoint and the 85% model-only ensemble—not merely the
weaker Llama endpoint—while preserving clean RAG accuracy. The next collection step is exactly one
clean RAG verdict for each of 100 development claims and each of the three enabled victims (300
executions). Fact2Fiction's clean-correct filter is then applied separately per victim before any
attacked tasks are scheduled.
