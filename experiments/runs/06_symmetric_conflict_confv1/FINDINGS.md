# Experiment 06 — findings

Run: `experiments/runs/06_symmetric_conflict/`. Full numbers in `exp06_report.md`, every row in
`results_{clean,poisoned}_vs_mo.json`.

## What this run fixed

Three methodological defects invalidated every earlier conflict measurement. All three are gone:

| defect | earlier runs | here |
|---|---|---|
| clean and poisoned answered *different* question sets | two independent draws of stages 1&2 | one shared set, posed once (pass A) |
| unanswerable questions silently dropped | `approach_question_batch` deletes them | `approach_question` per question; a retrieval failure becomes a `NONE` **row** |
| the "controlled" fix was one-sided | questions drawn from the poisoned run, so only the clean side could have a NONE | both sides can, and do (10 clean, 8 poisoned) |

10 claims x 10 questions = 100 questions, answered by clean InFact stages 3&4, poisoned InFact
stages 3&4, and a retrieval-free model-only reasoner. Two tables of exactly 100 rows each,
asserted before the report is written.

## Headline: the signal is far weaker than previously reported

| comparison | rows | conflicts | rate |
|---|---|---|---|
| clean InFact vs model-only | 100 | 44 | **44.0%** |
| poisoned InFact vs model-only | 100 | 52 | **52.0%** |

**+8.0 points, ratio 1.2x.**

Earlier figures (2.1x uncontrolled, 2.3x controlled) were **artefacts of the three defects above**.
They do not survive a clean measurement.

## The three results that undermine the hypothesis

**1. Planted and authentic evidence are indistinguishable.**

| poisoned-side evidence | rows | conflict rate |
|---|---|---|
| planted | 83 | **55.4%** |
| authentic | 9 | **55.6%** |
| NONE (retrieval failed) | 8 | 12.5% |

The previously reported "planted 28.7% vs authentic 5.0% = 5.7x" does not replicate. The authentic
cell is only 9 rows, so this is weak evidence of *no* separation rather than strong evidence — but
there is no hint of one.

**2. The clean-side false-alarm floor is 44%.** On an un-poisoned knowledge base, model-only
disagrees with retrieval on nearly half the questions. An 8-point lift over that floor is not
usable.

**3. On the claims where the attack actually succeeded, the signal is exactly zero.**

| subset | vs clean | vs poisoned |
|---|---|---|
| attack flipped the verdict | 31/50 = 62.0% | 31/50 = **62.0%** |
| attack did not flip | 13/50 = 26.0% | 21/50 = 42.0% |

Verified this is not a bug: 0 misaligned questions between tables, only 1/100 rows has identical
InFact answer text, 36/100 rows carry different labels, and within the flipped subset 20/50 rows
differ. The totals coincide at 31 by chance; per-row disagreements cancel. The entire +8 points
comes from claims where the attack *failed*.

## Why the floor is 44% — verified, not assumed

Sampling the clean-side conflicts shows the driver is **structural, not an adjudicator defect**
(the failure mode that ruined the v2 prompt). InFact's sub-questions are written for a retriever:

> "What government agency announced the legal action or settlement?"
> "What is the origin and publishing source of this claim, and what supporting evidence does that
> source provide?"

A closed-book model cannot answer those and should not be expected to. 36 of the 100 model-only
answers are `no_recollection`, and on the clean side 52.8% of those are labelled conflict — a
"conflict" that reports only that the model lacks document-level detail, carrying no information
about poisoning.

Four sources of clean-side conflict, from a sample of the 42:

| source | example |
|---|---|
| information asymmetry (dominant) | InFact: "the DOJ filed suit against Vitas Hospice Services"; model-only: no recollection |
| model-only is wrong | InFact: `$75 million`; model-only: `$200 million` (self-declared `direct_recall`, confidence 0.8) |
| **clean RAG is wrong** | InFact: "Matt Gaetz was involved with Vitas"; model-only: it was his father **Don Gaetz** who co-founded VITAS — *model-only is correct here* |
| precision dispute | InFact: "through mid-October 2020"; model-only: "29 Feb - 30 Oct 2020" |

## `answer_basis` — the falsifiable check, and it mostly fails

`answer_basis` (`direct_recall` / `inference` / `no_recollection`) was added so a denial from
memory could be told apart from a denial by inference and from having no knowledge at all. If the
three levels do not separate, the model is confabulating its own basis.

| basis | clean | poisoned | difference |
|---|---|---|---|
| `direct_recall` (n=28) | 39.3% | **64.3%** | **+25.0** |
| `inference` (n=36) | 38.9% | 36.1% | -2.8 |
| `no_recollection` (n=36) | 52.8% | 58.3% | +5.5 |

`inference` is **inverted** and `no_recollection` is near-flat, so the field is not a clean
discriminator. But `direct_recall` separates sharply, and the per-claim distribution is plausible
rather than random — claim 8 (2020 US election fraud) produced 6 `direct_recall` / 0
`no_recollection`; claim 5 (Syria OPCW) produced 0 / 6, matching how well-covered those topics
are. So the field measures *something*; 28 rows is too few to say what.

## The one solid positive result

**Answerability asymmetry: 9 of 100 questions were answerable by the poisoned KB but not by the
clean one.** Planted evidence manufactures answerability. Claim 3 is the clearest case — clean KB
6/10, poisoned KB 10/10 with 9 of the 10 answers drawn from planted documents.

This needs no model-only side at all and is unaffected by everything above.

Related: 83 of the poisoned KB's 92 answers (90%) come from planted documents, from a poison
budget of only 8% of the corpus by document count — roughly a 9x amplification, produced by the
query-concatenation and answer-first fabrication in the attack.

## Consequences

- **"Model-only conflict rate" as a poisoning detector does not hold up.** Any earlier
  recommendation built on the 2x figures — in particular replacing run 05's stage-5 confidence
  scoring with it — has no basis.
- Remaining leads: (a) **answerability asymmetry**, model-free and robust; (b) the
  **`direct_recall` subset**, which would reframe the defense as "trust the model's objection only
  where it genuinely knows the matter" rather than "count disagreements".
- **Poison budget caveat:** `poison_rate = 0.08` yields 90% planted adoption. This is a
  *favourable* regime for any defense. A 1-3% budget is the harder test and requires re-running
  the attack (attacker LLM cost).
- Sample caveat: 10 claims / 100 questions. The authentic (n=9) and `direct_recall` (n=28) cells
  are thin.

## Reproducing

```bash
P=/home/ubuntu/.venv312/bin/python3.12
R=experiments/runs/06_symmetric_conflict
$P experiments/exp06_pose_questions.py --run-dir $R
$P experiments/exp06_answer_infact.py --kb clean    --run-dir $R
$P experiments/exp06_answer_infact.py --kb poisoned --run-dir $R
$P experiments/exp06_answer_model_only.py --run-dir $R
$P experiments/exp06_adjudicate.py --run-dir $R --expect 100
```

Passes B and C must be separate processes: the two vendored `infact` copies cannot share an
interpreter. Pass D touches no KB and can run concurrently with B or C.
