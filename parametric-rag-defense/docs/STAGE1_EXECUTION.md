# Stage 1 execution and artifact protocol

Stage 1 freezes independent model-only and RAG endpoint outputs so later arbitration experiments
cannot regenerate favorable answers. Gold labels are joined only by evaluation scripts.

## 1. Model-only collection

The main configuration is `configs/stage1_matrix.json`. It contains four target models, although
the Qwen 397B model is disabled until a credential accepted by NVIDIA's development endpoint is
available. Production credentials are read from Git-ignored `.env` at call time and are never
included in request keys or artifacts.

Run a small format pilot:

```bash
PYTHONPATH=src python3 scripts/run_stage1_internal.py \
  --claims 0,6,26,43 --workers 4
PYTHONPATH=src python3 scripts/summarize_stage1_internal.py \
  --claims 0,6,26,43
```

Run and verify the complete development split:

```bash
PYTHONPATH=src python3 scripts/run_stage1_internal.py --workers 4
PYTHONPATH=src python3 scripts/check_stage1_internal.py
PYTHONPATH=src python3 scripts/summarize_stage1_internal.py \
  --output artifacts/evaluation/stage1_internal_development.json
```

The active development set contains 100 balanced `Supported`/`Refuted` claims, matching
Fact2Fiction's first eligibility filter. The 100-claim balanced locked set remains unopened. A
separate 20-claim conflict/NEI diagnostic preserves the original non-binary development outputs.
Normalized claim text/date prompts are unique within and across all three partitions; prior split
manifests are archived so the objective duplicate-removal lineage is inspectable.
Fact2Fiction's second filter is applied per victim after clean RAG collection: attacked paired
analyses use only claims that the same victim answered correctly in the clean condition.

Do not use `--allow-locked-test` until the prompts, model roles, attack adapters, and analysis plan
are frozen. Re-running a development command reuses content-addressed cache entries. A manifest is
merged only when its exact configuration and prompt digests match. The adjacent `.sha256` lock file
prevents even a whitespace-only prompt edit from silently issuing a second set of calls.

Switchable reasoning models use non-thinking mode in the main reliability/cost-controlled sweep.
The disabled `reasoning_sensitivity_profiles` specify a 16,384-token native-thinking sensitivity
analysis. If a reasoning profile is stronger, it must be reported as another standalone model-only
baseline. Hidden reasoning is never persisted or passed downstream.

## 2. Poisoning budgets

The two strength axes answer different questions and must not be plotted as if their x-values were
equivalent.

- Original PoisonedRAG sensitivity: `N=1,...,10` malicious documents per target query, with
  retrieval `k=5`; `N=5` is the paper default. `N=0` is our clean reference.
- Fact2Fiction sensitivity: nominal rates 0.1%, 0.5%, 1%, 2%, 4%, 8%, 12%, and 16% of the
  claim-specific evidence pool. The paper's primary table uses 1%, 2%, 4%, and 8% and reports an
  average clean pool size of 823.4 evidence items.

The Fact2Fiction reference implementation converts a fractional rate with
`max(1, int(Ni * rate / (1-rate)))`. Integer rounding means nominal rates can collapse to the same
injected count on small pools. Therefore every RAG artifact records the clean count, injected
count, realized final-corpus fraction, retrieved count, and retrieved-poison count. Analyses use
both the nominal condition and realized counts.

## 3. RAG adapter boundary

Attack/victim implementations write JSONL records; this repository validates and stores them with:

```bash
PYTHONPATH=src python3 scripts/ingest_stage1_rag.py adapter-output.jsonl \
  --tier development_sweep
PYTHONPATH=src python3 scripts/check_stage1_rag.py --tier development_sweep
```

Each JSONL record has exactly four top-level fields:

```json
{
  "task_key": "task key from artifacts/runs/stage1/task_matrix/rag_development_sweep.jsonl",
  "judgment": {
    "verdict": "Supported",
    "confidence": 0.72,
    "justification": "Concise final justification without a URL.",
    "questions": [
      {
        "question": "A generated fact-checking question",
        "status": "answered",
        "answer": "The adopted answer",
        "selected_rank": 1,
        "evidence": ["Source-normalized evidence excerpt without a raw URL"]
      }
    ]
  },
  "audit": {
    "clean_documents_before_injection": 823,
    "poison_documents_injected": 8,
    "realized_poison_fraction": 0.009626955475330927,
    "retrieved_documents_total": 5,
    "retrieved_poison_documents": 2
  },
  "provenance": {
    "upstream": "Fact2Fiction adapter",
    "upstream_commit": "full Git commit",
    "source_artifact_sha256": "digest of the raw upstream result"
  }
}
```

The ingester rejects unknown task keys, duplicates, secrets, gold-label fields, inconsistent
realized rates, impossible retrieval counts, raw URLs, malformed judgments, and attempts to
overwrite an existing task with different content. Attack targets and gold remain in separate
evaluation metadata and are never made available to Stages 3 or 4.

The current upstream Fact2Fiction/InFact copy does not natively support NVIDIA endpoints and uses
machine-specific paths. `scripts/run_stage1_rag_scan.py` is the dedicated NVIDIA adapter; legacy
outputs are not silently relabeled as results from these models. Its preserved components and
initial-scan approximations are specified in `docs/STAGE1_RAG_SCAN_PROTOCOL.md`.
The completed development measurements and their limitations are reported in
`docs/STAGE1_RAG_SCAN_RESULTS.md`.

## 4. Execution tiers

| Tier | Split | Conditions | Attack seeds | Purpose |
|---|---|---:|---:|---|
| `development_sweep` | 100 development | clean + Fact2Fiction 0.1%, 1%, 4%, 8% | 1 | initial signal discovery |
| `locked_primary` | 100 locked | clean + 8 preregistered attacked strengths | 3 | primary paired comparisons |
| `locked_strength_curve` | 100 locked | clean + all 18 attacked strengths | 1 | full robustness curves |

Internal judgments are cached once per claim, model, and decoding seed and reused across every RAG
condition. They do not multiply by the number of attack strengths.

After collection, generate both the gold-joined evaluation summary and the non-evaluative run
ledger:

```bash
PYTHONPATH=src python3 scripts/summarize_stage1_internal.py \
  --output artifacts/evaluation/stage1_internal_development.json
PYTHONPATH=src python3 scripts/audit_stage1_internal.py \
  --output artifacts/runs/stage1/development/internal_endpoint/audit.json
```

The immutable per-call cache is the authoritative raw artifact. Manifests map each claim/seed to a
cache key; superseded scope manifests live under `internal_endpoint/history/`; the audit adds file
digests, coverage, finish reasons, token usage, provider model IDs, and latency summaries. Together
these retain enough information to reuse every completed endpoint response without another model
call.

The completed RAG collection is checked and joined to the cached model-only endpoints with:

```bash
.venv/bin/python scripts/check_stage1_rag_scan.py
.venv/bin/python scripts/summarize_stage1_rag_scan.py
```
