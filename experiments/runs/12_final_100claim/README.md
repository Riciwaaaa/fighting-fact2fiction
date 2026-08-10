# 12_final_100claim/ — the headline result

The final 100-claim experiment, pooled and scored. **Read `report.md` and `metrics.csv` here;
the two directories it draws from are raw pipeline output, not results.**

```
report.md              the write-up
metrics.csv            accuracy, per-class precision/recall/F1, macro-F1, per arm
verdicts_pooled.json   all four arms' 100 verdicts, backfilled rows flagged
```

Regenerate with `experiments/exp08_final_report.py` (pure analysis, no LLM calls, seconds).

## Where the 100 claims live

Seed 42, 50 gold-Supported / 50 gold-Refuted, drawn from AVeriTeC dev. The claim set is one
sample; it is split across two directories only because Fact2Fiction could not attack all of it:

| directory | claims | why |
|---|---|---|
| `10_verdict_84claim/` | 84 | the ones Fact2Fiction attacked — full A–F pipeline, all four arms |
| `11_cm_only_16claim/` | 16 | the ones it skipped; no poisoned corpus exists, so only arms C, M and CM were run |

Fact2Fiction attacks a claim only if the clean fact-checker already got it right — it reports an
attack success rate, and a verdict has to be correct before it can be flipped. The 16 claims here
failed that check.

**For those 16, the poisoned arms are not missing.** An unattacked claim's poisoned knowledge base
is byte-identical to the clean one, so `P` is `C` and `P+M` is `CM` there. `exp08_final_report.py`
backfills them on that basis and flags every backfilled row. Reporting `P`/`P+M` at n=84 while
`C`/`M` sat at n=100 would compare arms over different claim sets.
