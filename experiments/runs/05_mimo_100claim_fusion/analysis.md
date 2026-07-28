# Evidence-fusion defense analysis (mimo_v25_pro)

Complete claims (gold + all 4 systems present): **96** of 100.

## T1 — Defense success (attack-flipped claims)

- Claims the attack flipped off gold: **39**
- Of those, recovered by the fusion defense: **15** (38%)
- Regressions (poisoned InFact right, fusion wrong): **7** [22, 41, 53, 90, 103, 118, 146]

Per-system accuracy on the complete set:

| System | Accuracy |
|---|---|
| model_only | 0.802 |
| clean_infact | 0.927 |
| f2f_poisoned_infact | 0.594 |
| fusion_defense | 0.677 |

## T2 — Confidence calibration vs held-out is_fake

Mean fusion-assigned confidence for retrieved InFact evidence, split by whether the evidence was actually planted by the attack (is_fake). is_fake is NEVER shown to any prompt; it is used here only as held-out ground truth.

| InFact evidence | N | Mean confidence |
|---|---|---|
| authentic (is_fake=False) | 159 | 0.829 |
| planted (is_fake=True) | 709 | 0.616 |

## T3 — Corroboration label vs held-out is_fake

| InFact evidence | corroborated | uncorroborated | contradicted | None |
|---|---|---|---|---|
| is_fake=False | 127 | 20 | 11 | 0 |
| is_fake=True | 384 | 96 | 229 | 0 |

## T4 — Pairwise system agreement (of 96 complete claims)

| | model_only | clean_infact | f2f_poisoned_infact | fusion_defense |
|---|---|---|---|---|
| model_only | 96 | 80 | 56 | 74 |
| clean_infact | 80 | 96 | 50 | 62 |
| f2f_poisoned_infact | 56 | 50 | 96 | 74 |
| fusion_defense | 74 | 62 | 74 | 96 |

