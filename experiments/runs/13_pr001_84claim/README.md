# 13_pr001_84claim/ — poison rate 0.01

Same 84 claims, same questions, same clean and model-only answers as `10_verdict_84claim/`
(copied verbatim — neither depends on the poison rate). The only thing recomputed here is what
the *poisoned* knowledge base returns, and everything downstream of it:

```
answers_poisoned.json        pass C against dev_fact2fiction_infact_0.01
results_poisoned_vs_mo.json  pass E, poisoned side only
merged_records_poisoned.*    the merged record for arm P+M
verdicts_{P,PM}_dropempty.json
```

Arms C and M are not re-run: no retrieval poisoning touches them, so 10/'s values hold.

Compare against `10_verdict_84claim/` (rate 0.08) and, once run, the 0.02 and 0.04 directories.
