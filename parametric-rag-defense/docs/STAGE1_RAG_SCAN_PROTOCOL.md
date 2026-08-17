# Stage 1 clean RAG and initial Fact2Fiction scan

This protocol is the first matched RAG collection on the 100-claim balanced binary development
split. It is a signal-finding run, not yet the publication-grade attack reproduction.

Collection completed on 2026-08-09: 300/300 clean endpoints and 936/936 attacked endpoints passed
the independent audit. See `STAGE1_RAG_SCAN_RESULTS.md` for measurements and interpretation.

## Frozen endpoints and strengths

The victims are Llama 3.1 70B Instruct, Qwen 3.5 35B-A3B, and GLM 5.2 through NVIDIA's production
endpoint. Each model receives the same pipeline and one decoding seed. The clean run contains 300
endpoints. The attacked run is scheduled only after applying Fact2Fiction's second filter separately
to each victim: the victim's clean verdict must equal the binary gold label.

The four nominal corpus fractions are 0.1%, 1%, 4%, and 8%. They cover a minimum-document regime,
the paper's headline 1% regime, and two stronger points from the paper's core curve. The exact
released formula is `max(1, int(Ni * rate / (1-rate)))`; every artifact also stores the realized
fraction because integer rounding is claim-dependent.

## Pipeline

The implementation preserves the research-relevant parts of the released InFact/Fact2Fiction
pipeline while removing machine-specific paths and unsupported providers:

1. Generate ten independent fact-checking questions and one retrieval query per question.
2. Retrieve five documents per query from the official claim-specific AVeriTeC development store
   with `Alibaba-NLP/gte-base-en-v1.5` and Euclidean nearest-neighbor ranking.
3. Answer the ten questions from retrieved evidence, then produce a binary Supported/Refuted
   verdict and justification.
4. For clean-correct claims, expose that victim's questions and justification to a targeted attack
   planner, flip the target verdict, allocate importance weights, fabricate evidence, and prefix
   surrogate retrieval queries.
5. Inject the exact number of documents for each rate, rerun retrieval/answering/judgment, and
   report both verdict degradation and poison retrieval exposure.

The implementation batches question answering into one LLM request instead of the upstream
result-by-result loop. For the initial scan it also generates at most 12 diverse poison blueprints
per victim/claim and deterministically expands them to the exact 8% budget; the four strengths use
nested prefixes of that corpus. This reduces calls enough for broad three-model signal discovery,
but it may change attack diversity and retrieval collisions. A publication result must replace the
expansion with independently generated poison documents and include an exact-upstream sensitivity
run. Every attacked artifact records this approximation in provenance.

## Reproducible commands

Install the optional RAG environment and download the official 11.5 GB store:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e '.[rag]'
curl -L --continue-at - --retry 8 --retry-all-errors \
  -o artifacts/data/averitec/dev_knowledge_store.zip \
  https://huggingface.co/chenxwh/AVeriTeC/resolve/main/data_store/knowledge_store/dev_knowledge_store.zip
```

Extract only the selected claims, hash the source archive, and build their indexes:

```bash
.venv/bin/python scripts/prepare_stage1_kb.py --device cuda:0 --batch-size 32
```

Run the clean collection, then the clean-correct poisoned scan. All commands resume from immutable
LLM cache entries and endpoint artifacts:

```bash
.venv/bin/python scripts/run_stage1_rag_scan.py --phase clean --workers 6
.venv/bin/python scripts/run_stage1_rag_scan.py --phase poison --workers 6
```

For a one-claim integration test, append `--models llama31_70b --claims 0`. Do not use locked-test
claim IDs until the method and analysis are frozen.

## Saved artifacts

- `artifacts/data/averitec/extraction_manifest.json`: archive size/hash, selected IDs, pool counts.
- `artifacts/data/averitec/index_manifest.json`: embedding model, dimension, indexed counts.
- `artifacts/cache/llm/`: exact prompt/parameter/raw response/parsed response for every LLM stage.
- `artifacts/runs/stage1/development/rag_traces/`: questions, searches, ranks, distances, excerpts,
  selected answers, verdicts, cache receipts, and token/latency metadata.
- `artifacts/runs/stage1/development/poison_corpora/`: blueprints, exact expanded documents, attack
  target, source cache receipts, and cached embeddings.
- `artifacts/runs/stage1/development/rag_endpoint/`: immutable normalized clean/attacked endpoints.
- `artifacts/evaluation/stage1_rag_clean_eligibility.json`: per-victim clean accuracy and eligible IDs.
- `artifacts/evaluation/stage1_fact2fiction_initial_scan.json`: per-rate accuracy, attack success,
  realized budgets, poison exposure, and claim-level predictions.
- `artifacts/evaluation/stage1_endpoint_complementarity.json`: same-model/multi-model endpoint
  contingency tables, oracle headroom, rescue rates, and aggregate intervals.
- `artifacts/runs/stage1/development/rag_scan_audit.json`: reconstructed coverage, validation,
  manifest digests, referenced cache count, and token usage.

Gold labels are used only when producing the two evaluation files. They are absent from prompts,
retrieval traces, LLM caches, poison generation inputs, and normalized endpoint artifacts.
