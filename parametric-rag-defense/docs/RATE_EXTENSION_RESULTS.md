# Frozen 0.1% rate-extension results

The extension protocol was committed before any 0.1% Stage C output was generated. It reused the
unchanged endpoint-only router, targeted proposition check, endpoint-only selector, decoding
settings, and condition-blind disagreement activation from the 1% study. All clean calls that had
identical requests were served from the immutable cache.

## Method-design gate

| Model | Clean RAG | Clean Stage C | 0.1% RAG | 0.1% closed-book | 0.1% Stage C | Design gate |
|---|---:|---:|---:|---:|---:|---|
| GLM 5.2 | 49/60 | 49/60 | 36/49 | 42/49 | **44/49** | Pass |
| Llama 3.1 70B | 44/60 | 43/60 | 39/44 | 31/44 | **40/44** | Pass |
| Qwen 3.5 35B | 45/60 | 41/60 | **37/45** | 35/45 | **37/45** | Fail |

GLM and Llama strictly exceeded both attacked endpoints and met the frozen clean-utility gate.
Qwen tied RAG and lost four clean cases, so it was not opened on validation.

For GLM, Stage C versus RAG had ten paired gains and two regressions (two-sided exact McNemar
`p=0.0386`), but only three gains and one regression over closed-book (`p=0.625`). For Llama, the
comparison with RAG was five gains and four regressions (`p=1.0`); the improvement over
closed-book was nine gains and zero regressions (`p=0.00391`). These design results determined
validation eligibility and are not confirmatory evidence by themselves.

## One-shot validation

| Model | Clean RAG | Clean Stage C | 0.1% RAG | 0.1% closed-book | 0.1% Stage C | Strict replication |
|---|---:|---:|---:|---:|---:|---|
| GLM 5.2 | 33/40 | **35/40** | 24/33 | **28/33** | **28/33** | No: ties closed-book |
| Llama 3.1 70B | **28/40** | 27/40 | **24/28** | 16/28 | 23/28 | No: one below RAG |

GLM retained a four-case improvement over poisoned RAG but did not beat model-only. Llama retained
a seven-case improvement over model-only but did not beat poisoned RAG. Neither model therefore
replicated the strict “above both endpoints” result. GLM improved clean accuracy by two cases;
Llama lost one clean case.

## Interpretation

The cached 0.1% endpoint oracle showed genuine selection headroom, and the design split suggested
that the frozen workflow could exploit it. The held-out result shows that the selector's margin is
too small and variable to support a model-general success claim. Lowering poison exposure does not
by itself solve arbitration.

The defensible conclusion is negative but useful: the current targeted workflow helps relative to
one endpoint consistently, but it has not learned a stable policy that identifies the better
endpoint on the remaining complementary cases. The 1% Llama result remains the only strict
held-out success, and 0.1% must not be substituted as an easier headline condition.

## Audited artifacts

- Freeze: `configs/stage4_rate_extension_freeze.json`
- Design routers: `artifacts/runs/stage3/stage3_same_model_rate001_design_v1/`
- Design Stage C: `artifacts/runs/stage4/stage4_same_model_rate001_design_v1/`
- Design evaluation: `artifacts/evaluation/stage4_same_model_rate001_design_v1.json`
- Validation routers: `artifacts/runs/stage3/stage3_same_model_rate001_validation_v1/`
- Validation Stage C: `artifacts/runs/stage4/stage4_same_model_rate001_validation_v1/`
- Validation evaluation: `artifacts/evaluation/stage4_same_model_rate001_validation_v1.json`

The design audit covered 318 routers and 107 Stage C outputs. The validation audit covered 141
routers and 54 Stage C outputs. Both audits reported zero identity, contract, same-model, prompt
privacy, or output-integrity failure.
