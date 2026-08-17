# Stage 1 RAG v1.2 results

Status: complete and independently audited on the 100-claim development split

Stage 1 v1.2 removes the source-origin leak found in v1.1. Every victim prompt uses neutral
per-question evidence IDs, masks raw URLs, and is scanned before the provider call. The v1.1
results remain directional history and are not inputs to later stages.

## Completeness and eligibility

| Victim | Clean correct / 100 | Clean accuracy |
|---|---:|---:|
| GLM 5.2 | 82 | 82% |
| Llama 3.1 70B | 72 | 72% |
| Qwen 3.5 35B-A3B | 73 | 73% |
| **Eligible victim/claim pairs** | **227** | — |

The repaired source representation changed eligibility relative to v1.1 (234 to 227 pairs), which
confirms that the leak was behaviorally material and could not be dismissed as cosmetic.

## Four-level scan

Micro-averages use the 227 clean-correct victim/claim pairs at every attack strength.

| Fact2Fiction fraction | Poisoned RAG | Same-model memory | Memory ensemble | RAG + all-memory oracle | Retrieved poison |
|---:|---:|---:|---:|---:|---:|
| 0.1% | 80.2% | 77.1% | 84.6% | 98.7% | 5.5% |
| 1% | 49.8% | 77.1% | 84.6% | 96.5% | 43.0% |
| 4% | 30.8% | 77.1% | 84.6% | 95.2% | 83.9% |
| 8% | 22.5% | 77.1% | 84.6% | 94.3% | 92.1% |

The oracle is analysis-only. It establishes complementarity, not a defense result. At the primary
1% condition, a workflow has roughly 12 points of headroom over the memory ensemble but must route
with high precision to realize it.

## Independent audit

- 300/300 clean and 908/908 attacked endpoint artifacts are present.
- Condition counts are exactly 300 clean plus 227 at each of four attack strengths.
- All 1,208 endpoint task keys and private trace keys are unique and expected.
- All referenced poison texts/embeddings match their recorded digests and row counts.
- The 2,946 referenced victim-call cache entries contain no raw URL or `clean:N` / `poison:N`
  source-origin marker.
- Total referenced use was 9,717,533 tokens (8,748,882 prompt; 968,651 completion).

Generated sources:

- `artifacts/evaluation/stage1_rag_v1.2_clean_eligibility.json`
- `artifacts/evaluation/stage1_rag_v1.2_initial_scan.json`
- `artifacts/evaluation/stage1_rag_v1.2_endpoint_complementarity.json`

