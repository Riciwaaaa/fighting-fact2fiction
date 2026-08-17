# Historical four-label internal-endpoint diagnostic

Date: 2026-08-08

Scope: 50 development claims (10 Supported, 20 Refuted, 10 Conflict, 10 NEI), three decoding
seeds per claim

This was the repository's first completed internal-endpoint sweep. It is retained as an
exploratory diagnostic, not part of the primary Fact2Fiction-compatible denominator. The active
study instead uses 100 balanced binary development claims and 100 balanced binary locked claims.
The 20 non-binary claim IDs are explicitly retained as `four_label_diagnostic` in the split
manifest, while the superseded endpoint manifests and all immutable cache records remain on disk.

## Reliability and performance

- Llama 3.1 70B, Qwen 3.5 35B-A3B, and GLM 5.2 each completed 150/150 outputs.
- There were no provider-call failures, contract failures, or length-truncated responses.
- Qwen 3.5 397B-A17B was unavailable because the supplied production credential was not accepted
  by NVIDIA's separate development endpoint.

| Model | Accuracy | Macro-F1 | Three-seed unanimity | Mean reported confidence |
|---|---:|---:|---:|---:|
| Llama 3.1 70B | 42% | 35.5% | 94% | 0.531 |
| Qwen 3.5 35B-A3B | 50% | 31.4% | 94% | 0.942 |
| GLM 5.2 | 50% | 40.9% | 72% | 0.843 |

| Model | Supported (n=10) | Refuted (n=20) | Conflict (n=10) | NEI (n=10) |
|---|---:|---:|---:|---:|
| Llama 3.1 70B | 40% | 45% | 0% | 80% |
| Qwen 3.5 35B-A3B | 60% | 95% | 0% | 0% |
| GLM 5.2 | 60% | 80% | 10% | 20% |

Qwen emitted only Supported or Refuted majority verdicts despite the four-label prompt. Llama was
much more willing to abstain: 26/50 majority verdicts were NEI and 73/150 samples used
`insufficient_knowledge`. GLM was between those extremes and had the strongest macro-F1.

## Cross-model diagnostic

| Diagnostic | Result |
|---|---:|
| Three-model majority accuracy | 52% |
| Three-model oracle (any endpoint correct) | 70% |
| Claims where all three endpoint majorities agree | 40% |

- Llama vs Qwen: 29 disagreements; only Llama correct on 9 and only Qwen correct on 13.
- Llama vs GLM: 23 disagreements; only Llama correct on 7 and only GLM correct on 11.
- Qwen vs GLM: 10 disagreements; each was uniquely correct on 4.

The 18-point oracle/majority gap motivated LLM arbitration, but is not itself a deployable method
result. This historical run neither detects poisoning nor shows an improvement over model-only and
poisoned RAG; those claims require matched clean and attacked RAG outputs.
