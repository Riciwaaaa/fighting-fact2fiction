# Stage 1 internal collection log

Dates: 2026-08-08--2026-08-09 (America/Los_Angeles)

## Frozen request scope

- Dataset: AVeriTeC development file from the adjacent Fact2Fiction repository.
- Active development: 100 unique claims, 50 Supported and 50 Refuted.
- Locked test: 100 unique claims, 50 Supported and 50 Refuted; no endpoint outputs opened.
- Historical diagnostic: 20 unique claims, 10 Conflict and 10 NEI.
- Prompt: `internal_claim_v2`, SHA-256
  `aa237f7ef576b0cc093bb53b124d3cf3d93e645286efa5f3b489dd228876d8d3`.
- Decoding repeats: seeds 11, 29, and 47; temperature 0.2; top-p 0.7.
- Concurrency: four provider calls at a time, models executed sequentially.

## Collection events

1. Expanded the prior 50-claim development scope to 100 binary-label candidates while retaining a
   disjoint 100-claim locked set and the 20 non-binary historical diagnostic.
2. Collected Llama 3.1 70B, Qwen 3.5 35B-A3B, and GLM 5.2 internal judgments. A prior whitespace-only
   prompt change had correctly created a new content-addressed namespace; historical responses were
   retained rather than overwritten.
3. Qwen returned three invalid first attempts: one length-truncated response, one non-JSON response,
   and one response with six rather than at most five decisive propositions. Distinct format-repair
   requests succeeded. Both versions are immutable and linked by each manifest row.
4. The artifact audit revealed only 97 unique prompt keys among the initial 100 rows. An exact
   claim/date audit found one four-entry duplicate in development, a locked duplicate pair, and two
   development/locked overlaps. Without consulting endpoint correctness, duplicate IDs 207, 211,
   224, 203, 212, and 216 were removed and label-matched IDs 301, 346, 489, 13, 201, and 299 were
   added. Split lineage was archived.
5. Refreshed all manifests from cache. Only the three new development claims required provider
   calls: 3 claims × 3 seeds × 3 models = 27 calls. The other 873 final task outputs were reused.
6. Completeness validation passed for 3 models × 100 claims × 3 seeds = 900 final outputs.
7. Downloaded and hashed the official 11,537,899,362-byte AVeriTeC development knowledge store,
   extracted only the active 100 claim pools (81,326 documents), and built pinned GTE v1.5 indexes.
8. Collected 300/300 clean RAG endpoints. Per-victim clean-correct eligibility was 73 Llama,
   78 Qwen, and 83 GLM claims, for 234 victim/claim pairs.
9. Generated one victim-aware maximum attack corpus per eligible pair and evaluated nested 0.1%,
   1%, 4%, and 8% prefixes: 936/936 attacked endpoints.
10. Archived 60 pre-v1.1 smoke endpoints and their traces outside the active namespace. The final
    audit reconstructed all 1,236 expected task keys and found no missing, unexpected,
    noncanonical, cache-integrity, or poison-material failures.

## Generated artifacts

- `artifacts/runs/stage1/development/internal_endpoint/{model}.json`: active 300-row manifests.
- `artifacts/runs/stage1/development/internal_endpoint/history/`: superseded 50-claim,
  pre-deduplication 100-claim, and earlier prompt-scope manifests.
- `artifacts/cache/llm/entries/`: exact request and response for every base and repair attempt.
- `artifacts/runs/stage1/logs/`: Qwen repair, GLM collection, and unique-split refresh logs.
- `artifacts/runs/stage1/development/internal_endpoint/audit.json`: coverage, file digests, provider
  model IDs, attempts, finish reasons, token usage, and latency.
- `artifacts/evaluation/stage1_internal_development.json`: gold-joined per-claim and aggregate
  metrics.
- `artifacts/runs/stage1/development/{rag_endpoint,rag_traces,poison_corpora}/`: final v1.1 RAG
  artifacts and reusable attack material.
- `artifacts/evaluation/stage1_fact2fiction_initial_scan.json`: the four-level attack curve.
- `artifacts/evaluation/stage1_endpoint_complementarity.json`: RAG/internal complementarity and
  oracle headroom.
- `artifacts/runs/stage1/development/rag_scan_audit.json`: complete RAG integrity and usage audit.

The original malformed outputs, removed duplicate-scope mappings, and historical four-label outputs
remain recoverable. No locked endpoint output was generated in this collection.
