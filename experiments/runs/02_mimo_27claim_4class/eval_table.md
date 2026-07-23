# 4-system comparison (mimo, poisoned-KB defense) — N=27 claims

Gold distribution: {'Supported': 9, 'Refuted': 18}

## Primary metrics (2 gold classes: Supported, Refuted)

| System | Accuracy | F1 Supported | F1 Refuted | Macro-F1 | Off-label preds |
|---|---|---|---|---|---|
| model_only | 0.630 | 0.667 | 0.690 | 0.678 | 4 |
| infact | 1.000 | 1.000 | 1.000 | 1.000 | 0 |
| f2f_poisoned_infact | 0.481 | 0.167 | 0.686 | 0.426 | 7 |
| model_only_assisted_poisoned_infact | 0.222 | 0.182 | 0.370 | 0.276 | 16 |

## Full 4-class view

| System | Accuracy | F1 Sup | F1 Ref | F1 NEI | F1 Conf | Macro-F1 |
|---|---|---|---|---|---|---|
| model_only | 0.630 | 0.667 | 0.690 | 0.000 | 0.000 | 0.339 |
| infact | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 0.500 |
| f2f_poisoned_infact | 0.481 | 0.167 | 0.686 | 0.000 | 0.000 | 0.213 |
| model_only_assisted_poisoned_infact | 0.222 | 0.182 | 0.370 | 0.000 | 0.000 | 0.138 |
