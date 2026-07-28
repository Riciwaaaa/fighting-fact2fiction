# Evidence-fusion 4-system comparison (mimo_v25_pro)

## All claims — N=96 claims

Gold distribution: {'Supported': 25, 'Refuted': 71}

| System | Accuracy | F1 Supported | F1 Refuted | Macro-F1 | Off-label preds |
|---|---|---|---|---|---|
| model_only | 0.802 | 0.642 | 0.863 | 0.752 | 0 |
| clean_infact | 0.927 | 0.837 | 0.953 | 0.895 | 0 |
| f2f_poisoned_infact | 0.594 | 0.339 | 0.707 | 0.523 | 0 |
| fusion_defense | 0.677 | 0.392 | 0.780 | 0.586 | 0 |

## Legacy claims (dev 0-99, run-03 set) — N=51 claims

Gold distribution: {'Supported': 9, 'Refuted': 42}

| System | Accuracy | F1 Supported | F1 Refuted | Macro-F1 | Off-label preds |
|---|---|---|---|---|---|
| model_only | 0.804 | 0.583 | 0.872 | 0.728 | 0 |
| clean_infact | 1.000 | 1.000 | 1.000 | 1.000 | 0 |
| f2f_poisoned_infact | 0.647 | 0.182 | 0.775 | 0.478 | 0 |
| fusion_defense | 0.706 | 0.286 | 0.815 | 0.550 | 0 |

## New claims (dev 100+) — N=45 claims

Gold distribution: {'Supported': 16, 'Refuted': 29}

| System | Accuracy | F1 Supported | F1 Refuted | Macro-F1 | Off-label preds |
|---|---|---|---|---|---|
| model_only | 0.800 | 0.690 | 0.852 | 0.771 | 0 |
| clean_infact | 0.844 | 0.720 | 0.892 | 0.806 | 0 |
| f2f_poisoned_infact | 0.533 | 0.432 | 0.604 | 0.518 | 0 |
| fusion_defense | 0.644 | 0.467 | 0.733 | 0.600 | 0 |
