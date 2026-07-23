# 4-system comparison (mimo, poisoned-KB defense) — N=53 claims

Gold distribution: {'Supported': 9, 'Refuted': 44}

## Primary metrics (2 gold classes: Supported, Refuted)

| System | Accuracy | F1 Supported | F1 Refuted | Macro-F1 | Off-label preds |
|---|---|---|---|---|---|
| model_only | 0.868 | 0.667 | 0.918 | 0.792 | 0 |
| infact | 1.000 | 1.000 | 1.000 | 1.000 | 0 |
| f2f_poisoned_infact | 0.642 | 0.174 | 0.771 | 0.472 | 0 |
| subclaim_verified_poisoned_infact | 0.868 | 0.588 | 0.921 | 0.755 | 0 |

## Full 4-class view

| System | Accuracy | F1 Sup | F1 Ref | F1 NEI | F1 Conf | Macro-F1 |
|---|---|---|---|---|---|---|
| model_only | 0.868 | 0.667 | 0.918 | 0.000 | 0.000 | 0.396 |
| infact | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 0.500 |
| f2f_poisoned_infact | 0.642 | 0.174 | 0.771 | 0.000 | 0.000 | 0.236 |
| subclaim_verified_poisoned_infact | 0.868 | 0.588 | 0.921 | 0.000 | 0.000 | 0.377 |
