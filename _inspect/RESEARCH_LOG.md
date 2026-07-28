# Research log — run 05 and the diagnostic probes that followed

Everything done in this line of work, in order, with the numbers and the reasoning.
Written so a cold reader (or a fresh session) can pick up from here.

**Goal of the project:** defend a retrieval-based fact-checker (InFact) against the
Fact2Fiction knowledge-base poisoning attack **using the model's own internal knowledge**.
A defense that simply abandons retrieval does not count — the point is to use internal
knowledge to *correct* a poisoned RAG pipeline.

---

## Part 0 — What run 05 was

The refactor from run 03's asymmetric sub-claim defense to a **symmetric evidence-fusion
pipeline**, expanded from 53 to 100 binary AVeriTeC claims.

Design decisions (user-confirmed at planning time):

- 100 binary claims = run-03's 53 legacy + 47 new from dev id 100+, **no** "clean-InFact-was-
  correct" filter. `clean_infact` is redefined as *InFact's verdict on the un-poisoned KB,
  whatever it is* — the old `clean == gold` semantics was an artifact of that filter.
- Final verdict from a new **fusion judge** only (no InFact stage-G re-judge).
- **All `/created` oracle rules removed** from every prompt. `is_fake` is analysis-only.
  (Run 03's `TRUST_PROMPT` leaked this marker; that was a methodological problem.)
- Verification retrieval hits the **poisoned KB only** — a deployed system cannot reach a
  clean corpus.
- Model: `mimo_v25_pro` / `xiaomi/mimo-v2.5-pro` throughout; attacker `deepseek_v4_flash`.

Pipeline stages (`experiments/fusion_*.py`, run dir `runs/05_mimo_100claim_fusion/`):

| stage | script | what it does |
|---|---|---|
| M1 | `fusion_model_only.py` | model-only structured fact-check → sub-claims + memory evidence |
| M2 | `build_kb_index.py` | extend the KB kNN index to the new claims |
| M3 | `run_clean_infact.py` | clean InFact (un-poisoned KB) |
| M4 | `run_attacked_infact.py` | Fact2Fiction attack + poisoned InFact |
| M5 | `fusion_evidence_pool.py` | symmetric evidence pool + corroboration-probing retrieval |
| M6 | `fusion_confidence.py` | per-evidence confidence 0–1 + commentary |
| M7 | `fusion_judge.py` | final fusion verdict |
| M8 | `fusion_eval.py` / `fusion_analyze.py` | metrics + analysis |

All prompts are collected verbatim in **`_inspect/ALL_PROMPTS.md`**.

### Infrastructure problems solved along the way (all fixed, all real)

1. **Three distinct OOM sites** on this 4-core / 7 GB box. Root cause in each case:
   `sentence-transformers` pads every batch to its longest member, so a large batch on a
   resource-heavy claim (up to ~1500 resources, ~190 M chars) peaks at several GB.
   - `build_kb_index.py`: streamed truncation (never hold a claim's full text) + `embed_chunked`,
     `--batch-size` default 4.
   - `poisoned_kb.py`: same `_embed_chunked` fix.
   - `KnowledgeBase._embed_many` in **both** vendored `infact` copies (DEFAME and Fact2Fiction):
     the attack path passes ~1500 resources in one call; now sliced 64 at a time. DEFAME's copy
     was still at `batch_size=32` and was the more dangerous of the two.
2. **tmpfs disk exhaustion.** `/tmp` on this box is a RAM-backed tmpfs capped at 3.8 G. The
   poisoned-KB refit cache had grown to 3.1 G there, which both ate the RAM budget (compounding
   the OOMs) and eventually threw `[Errno 122] Disk quota exceeded`, killing M5 at claim 84.
   Cache moved to `.cache/poisoned_kb_cache` on real disk; `fusion_evidence_pool.py` updated.
3. **Session teardown killed background jobs.** Fixed by launching the master chain with
   `setsid` + `start_new_session=True` so it reparents to init (ppid=1).

---

## Part 1 — Run 05 results: the fusion defense underperformed

Final, N=96 (4 claims incomplete):

| system | accuracy |
|---|---|
| clean InFact (un-poisoned KB) | **0.927** |
| model-only (no retrieval) | **0.802** |
| f2f-poisoned InFact | **0.594** |
| **fusion defense (ours)** | **0.677** |

The attack costs −0.333. The fusion defense recovers only +0.083 — and lands **below plain
model-only (0.802)**. It recovered 15 of 39 attack-flipped claims (38%) and **introduced 7 new
errors** (claims 22, 41, 53, 90, 103, 118, 146).

Legacy-53 vs new-47 split matters: clean InFact is 1.000 on the legacy subset (by construction
of the old filter) but **0.844** on the new claims. The new subset is the honest baseline.

### Why it failed — three compounding causes

**(a) The corroboration probe is defeated by design.** Fact2Fiction injects a *mutually
consistent cluster* of fake documents. Verification queries search the same poisoned KB, so
"is there independent corroboration for this?" retrieves the fabrication's own supporting cast.
Measured: **54% of planted evidence was labelled `corroborated`**. Mean confidence separated
poorly — planted 0.616 vs authentic 0.829, a gap of only 0.21.

**(b) The evidence pool is numerically lopsided.** Across 96 claims:

| source | items | per claim |
|---|---|---|
| InFact side | 868 | 9.0 (82% of them planted) |
| model side | 401 | 4.2 |

InFact contributes **2.2×** the model side; **planted evidence alone outnumbers the entire
model side 1.8:1**. In 93 of 96 claims the InFact side had more items. Even with perfect
confidence scoring the judge is arbitrating from a skewed input; with imperfect scoring it is
a rout.

**(c) The failure is in stage 5, not stage 6.** The fusion judge behaves correctly given its
inputs — it weights high-confidence evidence as instructed. The confidence scores are simply
wrong. Case 92 (`_inspect/case_92.md`): 8 of 9 planted items scored ≥0.70, 7 labelled
`corroborated`; model-only had the right answer and was outvoted.

Case files: **`_inspect/case_22.md`** (regression), **`_inspect/case_92.md`** (failed recovery,
legacy), **`_inspect/case_104.md`** (failed recovery, new claim). Each has the full trace:
verdicts → model-only sub-claims → poisoned InFact Q&A → evidence pool with queries/retrieval/
confidence → fusion verdict → diagnosis.

---

## Part 2 — Probe: can model-only answer *InFact's own* sub-questions?

Motivation: the user recalled an earlier experiment where model-only often could not answer
sub-questions, and suspected it was a system bug.

Method (`experiments/tmp_probe_subq_modelonly.py`): InFact's real stages 1&2
(`pose_questions.md`, n=10, extracted with InFact's own `find_code_span`), then one model-only
CoT call per question. 5 claims, no KB touched.

**Result — 50 questions:** answered 27 (54%), uncertain 20 (40%), **unknown only 3 (6%)**.

So the earlier impression did not reproduce. More importantly, the `uncertain`/`unknown` labels
*undersell* the content: "UNESCO officials have not confirmed this claim; it is not a recognised
UNESCO declaration" was labelled `uncertain` yet is a decisive refutation. The `status` field
measures "can I state a positive fact", not "is this useful for the verdict" — and for Refuted
claims, knowing something *didn't* happen is exactly the evidence needed.

### Part 2b — feeding those answers into InFact stages 5&6

`experiments/tmp_probe_verdict.py` builds InFact's exact Q&A document from the model-only
answers (source line honestly says "no retrieved source"), then runs InFact's own `Judge` and
`DocSummarizer`. **5/5 correct**, including claim 6 which the fusion defense got wrong.

**This is NOT a proposed defense** — a retrieval-free InFact abandons RAG rather than defending
it, which is off-target for the research goal. It is reported only as evidence that model-only
answers carry enough signal to drive InFact's own judge.

---

## Part 3 — The hallucination problem, and the fix

Comparing the two retrieval-free routes on the same 5 claims (**`_inspect/compare_evidence.md`**)
exposed a structural issue.

### InFact's questions are presuppositional, and that induces hallucination

InFact writes questions for a *retriever*, so they take the claim's objects for granted
("what reason did **the letter** give?"). A retriever answers "no document found". A
retrieval-free model, told to answer and not to hedge, **fills the presupposition**.

On claim 0 (the Sean Connery letter — a Scoopertino spoof debunked in 2011), **4 of 10 answers
were outright fabrications**, including a cited-but-nonexistent passage in Walter Isaacson's
biography. The label still came out Refuted, **but the fabricated citation reached the published
justification** — label-only evaluation would have hidden this.

By contrast the pipeline's own `model_only` (which writes its *own*, non-presuppositional
questions — "**Did** Connery ever write to Jobs?") had **zero** fabrications.

Hallucination/gap tally over 5 claims:

| | pipeline `model_only` | probe (InFact questions) |
|---|---|---|
| outright fabrications | 0 | **6** |
| wrong dates/figures | 2 | 2 |
| self-contradictions | 1 | 1 |
| evidence volume | 4.4 stmts/claim | 10/claim (3.7× the text) |

Complementary failure modes: pipeline `model_only` is **clean but shallow** (misses provenance,
fact-check coverage, decisive specifics; on claim 6 it substituted a weaker number and undersold
a true claim). The probe is **broad and specific but credulous**.

### The fix (validated)

`MO_ANSWER_PROMPT` in `experiments/tmp_conflict_probe.py` adds a paragraph naming the failure
mode, makes **rejecting the question's premise a first-class answer**, bans un-recalled citations
outright, and adds a `premise_status` field (`premise_holds` / `premise_unverifiable` /
`premise_false`).

**Validated on claim 0: hallucinations went 4/10 → 1/20.** All four earlier fabrications became
correct refusals ("I have no knowledge of such a letter existing"). ~46% of answers now flag the
premise as unverifiable or false.

---

## Part 4 — The key result: MO-vs-InFact conflict as a poisoning signal

**This is the finding the defense should be built on.**

`experiments/tmp_conflict_probe.py`: for every sub-question InFact asked (in its clean run and
in its poisoned run), model-only answers the same question with no retrieval; an adjudicator
labels the relation `agree` / `conflict` / `mo_abstains` / `incomparable`. 20 claims
(10 attack-flipped, 10 not), 354 question-answer pairs.

### Headline (`_inspect/conflict_probe.md`)

| model-only compared against | comparable | conflicts | conflict rate |
|---|---|---|---|
| **clean** InFact | 113 | 13 | **11.5%** |
| **poisoned** InFact | 107 | 26 | **24.3%** |

### The sharper result — evidence-level, no confound possible

Within the *same* poisoned run, split by the withheld `is_fake` flag:

| poisoned-run evidence | comparable | conflicts | conflict rate |
|---|---|---|---|
| **planted** | 87 | 25 | **28.7%** |
| **authentic** | 20 | 1 | **5.0%** |

**5.7×.** And 25 of the 26 conflicts land on planted evidence — the signal barely touches
genuine evidence. Compare with the confidence stage it would replace (0.616 vs 0.829, 0.21 apart).

Crucially this probe **does not retrieve anything**, so it cannot be fooled by the poisoned
corpus's self-corroboration — the exact weakness that sank stage 5.

### A methodological question the user raised, and its resolution

*Are the clean and poisoned conditions answering the same questions?* **No — zero overlap
across all 354 pairs.** Two independent runs, each re-posing 10 questions.

Verified in code that this is **not** poisoning-induced: `InFact.apply_to` calls
`_pose_questions` first, on a freshly created `FCDocument(claim)`, and `PoseQuestionsPrompt`
fills only `[CLAIM]` and `[N_QUESTIONS]`. **Stages 1&2 never touch the KB.** The wording differs
purely by LLM sampling.

Residual confound is only at stages 3&4, where `approach_question_batch` drops unanswerable
questions — measured drop rates **10% (clean) vs 13% (poisoned)**, i.e. small and similar. So
the clean-vs-poisoned comparison is two draws from the same question distribution and is
broadly fair; the evidence-level split is airtight regardless.

*(I initially over-stated this confound as invalidating the comparison, then corrected it after
reading the code.)*

### Part 4b — the controlled three-way run (COMPLETE, 20 claims / 174 questions)

`experiments/tmp_controlled_conflict.py` removes even the residual confound: it takes each
claim's **poisoned-run questions** (whose poisoned answers and model-only answers already exist)
and re-runs **only InFact stages 3&4** against the **clean** KB, so clean KB / poisoned KB /
model-only all answer an identical question set. A `FactChecker` is built solely to obtain a
configured `procedure`; stages 1&2 and 5&6 are never invoked.

| model-only compared against | comparable | conflicts | conflict rate |
|---|---|---|---|
| **clean** KB answers | 103 | 11 | **10.7%** |
| **poisoned** KB answers | 107 | 26 | **24.3%** |

Difference **+13.6%**, ratio **2.3×** — matching the uncontrolled Part 4 result (11.5% / 24.3%).

**The strongest single row in this whole investigation** — same question, same model-only answer,
the *only* variable being whether the KB was poisoned:

| poisoned-run evidence | MO vs clean KB | MO vs poisoned KB |
|---|---|---|
| planted (n=149) | 10/84 = **11.9%** | 25/87 = **28.7%** |
| authentic (n=25) | 1/19 = 5.3% | 1/20 = 5.0% |

For the questions that planted evidence answered, model-only conflicts with the *clean* answer
11.9% of the time and with the *poisoned* answer 28.7% — a 2.4× jump with the question, the
answerer and the model-only answer all held fixed. This rules out "the question was hard" and
"model-only lacks knowledge here" as explanations. The authentic row barely moves (5.3% → 5.0%),
which is exactly the control behaviour one wants.

Split by whether the attack flipped the verdict: flipped 15.6% → 30.4%, not flipped 6.9% → 19.7%.

**Answerability, measured as a by-product:** the clean KB could not answer **21/174 (12%)** of the
questions the poisoned KB answered. Planted evidence manufactures answerability — a poisoning
fingerprint that needs no model-only side at all.

Output: `_inspect/controlled_conflict.{md,json}`.

---

## Part 5 — The adjudicator is under-counting (open issue)

Relation distribution over 354 pairs:

| side | agree | conflict | mo_abstains | incomparable |
|---|---|---|---|---|
| clean | 100 (56%) | 13 (7%) | 59 (33%) | 8 (4%) |
| poisoned | 81 (47%) | 26 (15%) | 59 (34%) | 8 (5%) |

**118 abstentions, of which 111 (94%) contain explicit negation** ("there is no record",
"I have no knowledge of any such"). And on the poisoned side, **55 of 59 abstentions sit on
planted evidence** — the bucket is far from randomly distributed.

Two readings:

| reading | planted | authentic | ratio |
|---|---|---|---|
| strict (current: abstain excluded) | 29% (25/87) | 5% (1/20) | **5.7×** |
| broad (abstain counted as denial) | 56% (80/142) | 21% (5/24) | 2.7× |

Strict has better specificity, broad has far better recall (80 vs 25 detections). For a defense,
recall matters more — missing a planted item is costlier than down-weighting a genuine one,
which other evidence can offset.

Logically the adjudicator is defensible ("I don't know X" ≠ "X didn't happen"). But for *this
task* the distinction is wrong: a model that knows Connery's dates, the Think Different lineup
and Jobs's death, yet has no trace of "Jobs publicly confirmed Connery's letter at a shareholder
meeting", is producing evidence. Real events leave traces in parametric memory; fabrications do
not — the same principle as corroboration probing, but probing **memory**, which cannot be poisoned.

Examples of every abstain/incomparable case: **`_inspect/abstain_incomparable.md`**.

---

## Part 6 — The binary adjudicator (v2), and what it cost

**User's ruling:** the adjudicator should decide *only* agree-or-conflict. The two parking labels
were an unforced error on my part — and many rows in them matter more than the ones v1 called
conflicts (e.g. claim 20, planted: InFact "the source is insufficient to say whether the chant is
'Modi'", model-only "no, it has been fact-checked as a misinterpretation").

`ADJUDICATE_PROMPT` v2 in `tmp_conflict_probe.py` has two labels and no escape hatch. Only the
adjudication was re-run (`tmp_readjudicate.py`); every model-only and InFact answer is read back
from the stored JSON, so v1 and v2 are an exact paired comparison, not a re-sampling.

### The design point that took two attempts

A blunt binary — "model-only saying *I have no knowledge of X* is always a conflict" — **inverts
the signal**. On claim 0 it produced clean 100% vs poisoned 80%. The reason: a *clean* InFact
answer is frequently itself negative ("no credible evidence Apple approached Connery; the letter
is a Scoopertino spoof"), and model-only's non-recall points the **same way**.

The working rule is **directional**: treat "I have no knowledge of X" as a substantive negative
answer, then it *conflicts* with "X is established/documented" and *agrees* with "X is
unattested/fabricated". Same data, same claim: clean 40% vs poisoned 80%.

### Three readings of the same 354 pairs

| reading | vs clean | vs poisoned | diff | ratio |
|---|---|---|---|---|
| v1 strict (parked rows excluded) | 13/113 = 11.5% | 26/107 = 24.3% | +12.8% | **2.1×** |
| v1 broad (parked rows = conflict) | 80/180 = 44.4% | 93/174 = 53.4% | +9.0% | 1.2× |
| **v2 binary (directional)** | 65/180 = 36.1% | 85/174 = 48.9% | +12.7% | 1.4× |

Where v1's parked rows landed: `mo_abstains` → 86 conflict / 32 agree; `incomparable` → 15
conflict / 1 agree. **The user's intuition was right in the main**: ~75% of the parked rows are
genuine conflicts.

### Correcting an earlier claim in this log

Part 4 reported "planted 28.7% vs authentic 5.0% = **5.7×**" as evidence of a strong signal.
**That framing chose the wrong metric.** The ratio is inflated by a 20-row authentic denominator,
and it comes with 28.7% recall — seven out of ten planted items missed. On precision/recall, which
is what matters for a detector:

| reading | flagged | TP | FP | precision | recall | F1 |
|---|---|---|---|---|---|---|
| v1 strict | 26 | 25 | 1 | 96.2% | 28.7% | 44.2% |
| **v1 broad** | 93 | 87 | 6 | 93.5% | **58.4%** | **71.9%** |
| v2 binary | 85 | 78 | 7 | 91.8% | 52.3% | 66.7% |

Counting the parked rows roughly doubles recall for 2.7 points of precision. F1 44% → 72%.

**But precision is barely above the base rate.** The poisoned evidence pool is 85.6% planted to
begin with, so 91.8% precision is only a **1.07× lift** (v1 strict: 1.18×). As a per-item "which
of these is fabricated" classifier, conflict is weak in all three readings. It is better read as a
**claim-level** poisoning indicator (poisoned > clean in 13/20 claims).

### The real cost: a 36% false-alarm floor on clean fact-checks

All 65 clean-side v2 conflicts are dumped and categorised in `_inspect/clean_side_conflicts.md`:

| group | n | what it is |
|---|---|---|
| A. model-only has no knowledge of a detail InFact retrieved | 28 | exact dates, company names, first-publication venue |
| C. hard core (v1 also said conflict) | 12 | **model-only is genuinely wrong** — irreducible |
| E. partial knowledge vs a specific figure | 11 | mostly harmless precision gaps |
| D. InFact's own answer is a non-answer | 10 | "the source does not contain this" |
| B. v1 said agree, v2 says conflict | 4 | **v2-introduced false positives** |

Roughly half of the 36% is fixable, from two prompt defects:

1. **The mechanical rules override direction.** "One side definite, the other cannot determine =
   conflict" mislabels pairs that plainly agree — InFact "the SCOTUS site lists 27 Oct 2020" vs
   model-only "I don't know what the site says; by common knowledge her tenure began 27 Oct 2020";
   InFact "first reported Friday 23 Oct 2020" vs model-only "late October 2020"; InFact "the
   source is insufficient to confirm an official announcement" vs model-only "no, Pogba never
   officially announced".
2. **Debunked-object descriptions.** A clean fact-check describing a *hoax in detail* (quoting the
   fake letter, its December 1998 dateline, the Scoopertino origin) reads as "X is established" to
   the adjudicator, while model-only has no trace of the hoax at all. At the **claim** level the
   two agree. The rule must key on the direction of the conclusion about the *claim*, not on
   whether the described object exists.

Group C (12 pairs, 6.7 points) is irreducible: model-only is simply wrong — e.g. dating the
Columbia 160k study to 21 May 2020 instead of 22 Oct 2020, or asserting India's imports from
China *rose* April–August 2020 when official data reported a 27.63% *decline*.

### User's next ruling, not yet implemented

**Dropped questions must be part of the comparison.** Right now every conflict measurement runs
*after* InFact discards unanswerable questions (see Part 7), so a question InFact could not answer
never enters the denominator. The rule to implement: InFact NONE + model-only also unable to
answer = `agree`; one side able, the other not = `conflict`.

---

## Part 7 — How InFact discards sub-questions, and what Fact2Fiction does about it

All discarding happens in **stages 3 & 4**; stage 5 (the Judge) discards nothing mechanically.
In `DEFAME/infact/procedure/variants/qa_based/base.py`:

1. **L64-65** — no search queries could be generated → `return None`.
2. **L71** — retrieval returned nothing → implicit `None`.
3. **L109-119** — the answerer returned NONE. The criterion is the last rule of
   `prompts/answer_question.md`: *"If the search result does not contain sufficient information to
   answer the Question, respond simply with NONE"*, detected by string match.
4. **L26, L31-32** — `approach_question_batch` keeps only non-`None` results. Its docstring says
   it plainly: *"Unanswerable questions are dropped."*

Two consequences worth remembering:

- **First-answerable-result wins** (L103-107): results are tried in retrieval order and the first
  one yielding a non-NONE answer returns immediately; the rest are never examined. One question
  ends up with exactly one evidence item and one URL.
- **Dropping is silent.** A dropped question does not appear in the Record at all, and `judge.md`
  binds the Judge to *"Use information only from the recorded evidence"*. Retrieval failure is
  therefore invisible to the Judge — it is never negative evidence.

**Fact2Fiction attacks precisely these two mechanisms**, by out-competing genuine documents rather
than by suppressing them:

| component | code | mechanism targeted |
|---|---|---|
| Query Planning — prepend a generated query to each fake corpus, `e = s_p ⊕ ẽ` | `attack_methods.py:199-226` | raises kNN similarity so planted docs rank **first** → wins "first-answerable-result" |
| Answer Planning — fix the adversarial answer first, then *"Craft a corpus that reflects the answer"* | `attack_methods.py:657` | planted evidence is **always sufficient** for its question, so it never triggers NONE; genuine documents that merely touch the topic often do |
| Budget Planning — weight sub-questions by influence on the justification, drop weight ≤ 5 | `infer_qa_weight` | concentrates the budget on the sub-questions that move the Judge |
| Question decomposition mirrors the victim | `pose_questions` | ensures coverage of the questions InFact will actually ask |

This is the structural reason the conflict signal works: InFact's silence on unretrievable
questions is invisible to its Judge, while model-only *can* say "no such thing is on record".

A second, model-free feature falls out of the same analysis and is **not yet measured**: *which
rank of retrieved result produced the answer*. Planted evidence is answer-first by construction,
so it should answer at rank 1 far more often than genuine corpus text. Recording the rank would
require a small patch to InFact's `generate_answer`.

---

## Open items / next steps

1. **Fix the two v2 adjudicator defects** (Part 6): demote the mechanical "definite vs cannot
   determine = conflict" rule below the directional test, and make the directional test key on the
   conclusion about the *claim* rather than on whether a described object exists. Target: clean
   side from 36% down to ~20% with the poisoned side largely unchanged.
2. **Include dropped questions in the comparison** (user's ruling, Part 6). Requires capturing
   InFact's NONE questions, which stages 3&4 currently discard without recording. Pairs then are:
   both unable = `agree`; one able, one not = `conflict`.
3. **Wire the conflict signal back into the pipeline**: replace the corroboration-probing
   confidence (stage 5) with "does model-only's independent answer to this evidence's
   sub-question conflict with it". Validate first on the claims fusion broke — **92, 104, 6** —
   then on the attack-flipped set.
4. **[QUEUED — user's idea, not urgent]** Take the parked cases and run a second model-only pass
   asking directly: *"be honest — do you find this evidence suspicious?"* Keep it as a **side
   experiment that does not touch the main line**.
5. **Two model-free features surfaced but not measured**: (a) answer rank — planted evidence
   should answer at retrieval rank 1 far more often (Part 7); (b) answerability asymmetry — a
   question the clean KB cannot answer but the poisoned KB can (Part 4b measured 21/174 = 12%).
6. When redesigning the fusion input, address the **2.2× evidence imbalance** (Part 1b): either
   give the model side a matching question budget, or normalise weight by source in the judge
   rather than letting it count items.
7. Residual hallucination is ~1/20 even after the fix; worth another look if the conflict signal
   becomes load-bearing.

## Caveats to carry forward

- 20 claims / 354 pairs is a probe, not a benchmark. The authentic-evidence cell is thin (n=20–25),
  so every authentic-side rate has wide error bars.
- Per-claim conflict rate has huge variance (0%–100%); this is an **evidence-level** signal, not
  a claim-level detector.
- **Conflict precision is barely above the base rate** (1.07×) because the poisoned pool is 85.6%
  planted. Do not read "91.8% precision" as a strong per-item classifier.
- Every conflict measurement to date runs **after** InFact discards unanswerable questions, so the
  denominators exclude exactly the cases where retrieval failed (Part 6 item 2, Part 7).
- "Attack did not flip" does **not** mean "KB not poisoned" — both conditions are poisoned; only
  the outcome differs.
- Adjudicator labels are LLM judgements and are not perfectly stable: claim 0 re-adjudicated at
  12/20 and 13/20 conflicts on two runs of the identical input.

## File map (`_inspect/`)

| file | contents |
|---|---|
| `RESEARCH_LOG.md` | this document |
| `ALL_PROMPTS.md` | all 6 pipeline prompts, in execution order |
| `case_22.md`, `case_92.md`, `case_104.md` | full per-claim failure traces |
| `compare_evidence.md` | pipeline `model_only` vs InFact-question probe: gaps and hallucinations |
| `subq_probe.{md,json}` | can model-only answer InFact's questions (Part 2) |
| `subq_verdict.{md,json}` | those answers through InFact stages 5&6 (Part 2b) |
| `conflict_probe.{md,json}` | the conflict-rate measurement, v1 four-label (Part 4) |
| `conflict_probe_v2.{md,json}` | same data re-adjudicated with the binary judge (Part 6) |
| `controlled_conflict.{md,json}` | controlled three-way run, v1 labels (Part 4b) |
| `controlled_conflict_v2.{md,json}` | controlled run re-adjudicated with the binary judge (Part 6) |
| `abstain_incomparable.md` | what the v1 parked labels look like (Part 5) |
| `clean_side_conflicts.md` | all 65 clean-side v2 conflicts, categorised (Part 6) |

Scripts are `experiments/tmp_*.py` (probes, temporary) and `experiments/fusion_*.py` (run-05
pipeline, permanent).
