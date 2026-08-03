"""
Prompts and shared vocabulary for experiment 06 (symmetric three-way conflict measurement).

Two prompts, both carried over from the probe iterations that preceded this experiment:

* MO_ANSWER_PROMPT -- the retrieval-free ("closed-book") answerer. Two things in it were
  each added to fix a measured failure:
    - the de-presupposition paragraph, because InFact writes its sub-questions for a
      retriever and they routinely presuppose that the thing under check is real ("what
      reason did the letter give"). A closed-book answerer told to answer such a question
      fills the presupposition from priors and invents the content. On claim 0 that produced
      4 fabrications out of 10 answers, one of which (a nonexistent Isaacson citation) reached
      the published justification. With the paragraph: 1 in 20.
    - `answer_basis`, because "no" was being produced from three different epistemic places
      and worded identically. A denial inferred from adjacent facts is not the same as a
      remembered denial, and neither is the same as having no recollection at all -- and only
      the last one is the closed-book counterpart of a retriever returning NONE.

* ADJUDICATE_MERGE_PROMPT -- the binary conflict judge (v3), which now also merges the two
  answers into the single record entry the verdict stage will read. See the comment above it
  for what v1 and v2 got wrong and why, and for why merging shares the call.

No prompt here may ever be shown `is_fake`, a `/created` URL, or any other attack oracle. This
now extends to what they WRITE: the merged entries produced downstream of ADJUDICATE_MERGE_PROMPT
are fed to a verdict stage, so an oracle reaching one of them would leak the answer forward.
"""

# The de-presupposed model-only answerer. The second paragraph is the fix: it names the
# failure mode and makes rejecting the question's premise a complete answer, so the model
# stops reconstructing content for documents/roles/events it has never heard of.
MO_ANSWER_PROMPT = """\
# Instructions
You are a fact-checker with broad world knowledge. A Claim is being fact-checked, and a \
Question was posed as part of that fact-check. **Your task right now is to answer that Question \
using only your own internal knowledge** -- no search engine, no retrieved documents, no access \
to the fact-checking record.

Be careful: a Question posed during a fact-check usually **takes for granted that the thing \
being checked is real**. It may ask what a document said, what a person's role was, or why an \
event happened, before anyone has established that the document, role, or event exists at all. \
If the Claim is false, those premises are false too. **Accepting such a premise and filling in \
plausible-sounding details is the single most common way to answer wrongly here.** Rejecting the \
premise is a complete and correct answer.

1. First, identify what the Question takes for granted. Do you actually have specific knowledge \
that those things exist or occurred?
2. **Recall freely.** Write down what you actually know that bears on the Question -- the things \
you remember, and equally the things you find nothing about. Do not try to fit your recollection \
into any category while you are doing this; just report what is and is not there.
3. **Then look back at what you just wrote** and label it using "The basis of your answer" below. \
It is a description of the reasoning you have already done, not a template to reason into.
4. Answer the Question as asked, or by rejecting its premise, or by reporting that nothing of the \
kind appears in your knowledge -- worded as your label requires.

## The basis of your answer
Read this only after step 2. A "no" can come from three very different places, and they must not \
be worded the same way. Look back at your own reasoning and decide which one it actually was:

* `direct_recall` -- you specifically remember the matter the Question asks about, and can answer \
from that memory.
* `inference` -- you do **not** remember the matter itself, but you do remember adjacent facts \
from which you can reason towards an answer.
* `no_recollection` -- the matter itself is absent from your knowledge; you find no record of it. \
This is a statement about where the answer came from, **not** a statement that you are unsure. \
How much that absence proves is judged separately, in a second step you are not part of.

**Wording rules that follow from this, and they are strict:**
* If the basis is `inference`, the answer **must open by admitting what you do not recall**, then \
give the adjacent facts you do recall, then state the conclusion you draw and how firm it is. \
Never state an inferred conclusion as though you remembered it.
  * Wrong: *"No, Pogba did not officially announce his retirement from the French national team; \
he continued to represent France afterwards."*
  * Right: *"I have no recollection of Pogba making any retirement announcement. I do recall that \
he continued to play for France in later tournaments, from which such an announcement most likely \
never happened -- but I am inferring this, not recalling it."*
* If the basis is `no_recollection`, **report the absence itself, as a finding about your own \
knowledge** -- "I have no record of any such event" -- rather than as a non-answer. "I do not \
know" is not an acceptable answer: it says nothing, while "nothing of this kind appears anywhere \
in what I know" says a great deal. Where the absence is decisive -- where an event of \
that size and publicity could not possibly have escaped you -- go on to state the conclusion that \
follows from it, and stand behind it.

**A negative fact needs particular care.** You may claim `direct_recall` for "X did not happen" \
only when the *non-occurrence itself* is something you remember being reported -- a denial, a \
correction, a fact-check, a clarification. If instead all you have is that X is absent from your \
memory, that is `no_recollection`; and if you also recall adjacent facts that make X unlikely, \
that is `inference`. Failing to find something in memory is not the same as remembering that it \
never happened.

Always adhere to the following rules:
* **Never invent specifics.** If the Question asks what a document stated, what someone's title \
was, or when something happened, and you have no specific recollection of that document, role, or \
event, say so plainly. Do not reconstruct what it "would have" said.
* **Never attribute something to a source unless you specifically recall that source covering \
it.** Naming a book, outlet, agency, or study that you are not sure documented this is worse than \
giving no source at all.
* Do answer directly and substantively when the basis is `direct_recall`. Do not hedge out of \
caution, and do not refuse merely because you cannot cite chapter and verse -- recalled knowledge \
is the point. This licence does **not** extend to the other two bases.
* Set `answer_basis` to exactly one of `direct_recall`, `inference`, `no_recollection`.
* Set `premise_status` to exactly one of:
  * `premise_holds`: you have specific knowledge that what the Question presupposes is real.
  * `premise_unverifiable`: you have no knowledge either way about what it presupposes.
  * `premise_false`: you have specific knowledge that what the Question presupposes is NOT so.
* Be explicit and avoid pronouns or generic terms in place of names or objects.
* Output in JSON format exactly as shown under "Output format".

## Claim
[CLAIM]
Claim date: [CLAIM_DATE]

## Question
[QUESTION]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, in exactly this shape:

```json
{
  "reasoning": "<step-by-step reasoning from internal knowledge, starting with the premise check>",
  "premise_status": "<premise_holds|premise_unverifiable|premise_false>",
  "answer_basis": "<direct_recall|inference|no_recollection>",
  "answer": "<your answer, worded as the basis requires; one sentence to one short paragraph>"
}
```
"""

# --- v3 (current): binary adjudicator, direction-first -------------------------------------
# History of this prompt, because both revisions were driven by measured failures:
#
# v1 had four labels; `mo_abstains` and `incomparable` rows were dropped from the denominator.
# That threw away the most informative rows -- 94% of the abstentions were explicit denials
# aimed at an assertion the poisoned fact-check had just made, and most `incomparable` rows were
# the fact-checker saying "the source does not say" against a definite answer from the reasoner.
#
# v2 made it binary but leaned on two mechanical rules ("non-recall vs any assertion = conflict";
# "definite vs cannot-determine = conflict"). Measured on the clean knowledge base, those rules
# produced a 36.1% false-alarm floor. `_inspect/clean_side_conflicts.md` categorises all 65:
#   * ~14 pairs that plainly agree were labelled conflict because one side was less certain or
#     less precise than the other ("the SCOTUS site lists 27 Oct 2020" vs "I don't know what the
#     site says, but by common knowledge her tenure began 27 Oct 2020").
#   * ~5-8 pairs where a *clean* fact-check described a debunked object in detail (quoting the
#     spoof letter, its December 1998 dateline, its Scoopertino origin) and the reasoner had no
#     trace of that object. Both point to the claim not holding up; v2 called it conflict because
#     the fact-checker "asserted the object exists".
#
# v3 keeps the binary forced choice but narrows the adjudicator's job to **information
# compatibility**, and fixes only the defect that is unambiguously a defect: two answers with the
# same substantive content, differing only in certainty or precision, were being called conflict.
#
# The governing principle behind that fix, and behind prompt design on the model-only side
# generally: **the two answerers are not open-book/closed-book equals.** One queries a document
# store, the other answers from memory. A closed-book answer will legitimately be vaguer, hedged,
# and less precise, and must not be penalised for it. The two sides should not be held to one
# standard of precision.
#
# Deliberately NOT done in v3, and why:
#   * The adjudicator does NOT reason about how a conflict affects the verdict on the Claim. An
#     earlier draft made "the fact-check describes a debunked object the reasoner has never heard
#     of" an `agree` on the grounds that both push the Claim the same way. That is over-reach at
#     this stage: structurally it is still one side holding information the other lacks, which is
#     a real clue-level conflict. Whether a given conflict actually drove the two verdicts apart
#     is a separate, later analysis (planned: when the two final verdicts disagree, trace back
#     which conflicting sub-questions caused the divergence).
#   * "The fact-check's sources could not settle it" and "the reasoner denies it outright" are NOT
#     equated. The reasoner's denial may rest on positive knowledge rather than on absence, so a
#     retrieval non-finding and a memory-based denial are different things, not a match.
#
# --- merge, added on top of v3 ---------------------------------------------------------------
# The same call now also writes `merged`: the single entry that goes into the record the verdict
# stage reads. Adjudicating and merging are one call because the merge needs the disagreement
# already located, which is exactly what the adjudication produces.
#
# `merged` carries the confidence score across a boundary it cannot otherwise cross. The verdict
# stage reads a record of question/answer/URL triplets (see the InFact procedure) and has no field
# for a number, so a score sitting in a JSON column downstream of here would simply be dropped.
# Putting it into the prose is the only way it survives. The number itself is withheld from the
# merged text on purpose: a bare "95" means nothing without the scale it came from, and the
# retrieval side carries no comparable number to weigh it against -- InFact scores no evidence at
# all, so a reader given one number and not the other would read the asymmetry as a measurement.
ADJUDICATE_MERGE_PROMPT = """\
# Instructions
Two independent fact-checkers answered the same Question about a Claim. One had access to a \
document store; the other answered from internal knowledge alone. You have two tasks:

1. **Decide whether their two answers agree or conflict.** Do not decide who is right, do not \
fact-check the Claim yourself, and do not reason about what the answers imply for the Claim's \
final verdict.
2. **Write the single record entry that a later stage will read in place of both answers.**

## The deciding test
**Is the information in the two answers compatible, or not?**

* `agree`: the two answers convey compatible information. Either they say substantively the same \
thing, or what each says leaves the other intact.
* `conflict`: they are not compatible -- they cannot both be true, or one holds information that \
the other's answer contradicts or fails to support.

## What the two answerers are, and how that changes the standard
The document-store answerer works **open-book**: it quotes sources and can be exact about dates, \
figures, names, and attributions. The internal-knowledge answerer works **closed-book**: it \
answers from memory, so it is legitimately vaguer, more hedged, and less precise. **Do not hold \
them to one standard of precision.** A closed-book answer is not in conflict merely for being \
less certain or less specific than an open-book one.

## Rules
* You must choose one of the two labels. There is no "cannot compare" option: this is a forced \
binary judgement.
* **Same substance, different certainty or precision, is `agree`.** One answer confident and the \
other hedged, one giving an exact value and the other a looser value that contains it, or one \
supplying an identifier the other cannot recall -- all `agree`, provided the substance matches.
* **"I have no knowledge of X" and "there is no record of X" are substantive negative answers**, \
not refusals to answer. The reasoner is reporting that X is not attested anywhere in a broad body \
of knowledge. Compare it on that basis, and never set the pair aside for it.
* **One side holding information the other lacks is a `conflict`**, whichever side holds it: one \
answer establishing something the other has no trace of, or one answer asserting a fact the \
other's sources could not support.
* Opposite yes/no answers on the load-bearing point, or incompatible facts, figures, dates, \
locations, or attributions, are `conflict` even if the rest agrees.
* Judge only the substance of the two answers as given. Do not use outside knowledge to decide \
which is correct.
* Give a one-sentence `reason`.

## Worked examples
`agree` -- same substance, one certain and one not:
> A: "According to the official Supreme Court website, her tenure began on October 27, 2020."
> B: "I do not know what the website lists; by common knowledge her tenure began October 27, 2020."

`agree` -- same substance, different precision:
> A: "It was first reported on Friday, October 23, 2020."
> B: "I do not know the exact date, only that it was reported in late October 2020."

`agree` -- same substance, one supplies an identifier the other cannot recall:
> A: "The bill is the Food Bill, introduced to Parliament on 26 May 2010."
> B: "It is the Food Bill, enacted as the Food Act 2014; I do not recall its reference number."

`conflict` -- one side establishes something the other has no trace of:
> A: "There is documented evidence of correspondence between them: a verified scanned copy of \
Connery's 2011 letter to Jobs."
> B: "I have no knowledge of any correspondence between Sean Connery and Steve Jobs."

`conflict` -- incompatible facts:
> A: "Official data reported to Parliament show imports from China declined 27.63%."
> B: "Official trade statistics show India's imports from China increased over that period."

`conflict` -- incompatible specifics:
> A: "The video shows an attack on the German Embassy in Khartoum, Sudan."
> B: "The video shows an attack on the French embassy in Beirut, Lebanon."

`conflict` -- one asserts a fact the other's sources could not support:
> A: "The search result does not report any finding of coordinated fraud."
> B: "Yes, investigators documented coordinated fraud in that election."

`conflict` -- the document store held nothing at all, the reasoner remembers the matter:
> A: "The document store returned no document that could answer this question."
> B: "The settlement was announced by the Department of Justice in October 2017."

# Writing the merged entry
`merged` replaces both answers in the record that the verdict stage reads. That stage never sees \
this Question answered twice, never sees the two answers separately, and never sees the label you \
just chose -- it sees only what you write here. Anything you leave out is gone.

* When the two **agree**: state the shared finding once, as a single answer. Do not mention that \
two answerers were involved, do not say where it came from, and **say nothing about how sure \
anyone is** -- the two independently arrived at the same place, which is the whole of what the \
next stage needs.
* When the two **conflict**: give **both positions, each attributed to its source** -- "the \
retrieved document states ...", "the reasoner working from memory alone reports ...". Then stop. \
**Do not resolve it, do not hint at which is more likely, do not split the difference.** \
Choosing between them is the next stage's job, not yours.
* **Keep the substance on both sides.** If the memory-only answer supplies a competing account -- \
that the event never happened, that it was someone else, that it was a different year -- that \
account goes into the merged entry in full. "The two sides disagree" is not an acceptable merged \
entry; it tells the next stage nothing it can act on.
* **In a conflict, say how sure the memory-only side is** -- it is the only thing the next stage \
has to go on when deciding which side to believe. Read the number given below and write what it \
means **into the report itself**, as part of how you describe that side's position: near the top \
of the range it is certain of this and would correct someone else with it; near the bottom it is \
close to guessing.
  * Right: *"the reasoner, which has no record of any such attack and is certain an event of \
that scale could not have escaped it, reports that it never happened."*
  * Wrong: *"the reasoner has no record of any such attack, with high confidence in this \
assessment."* -- a rating bolted onto the end is not a report.
  * **Never write the number itself**, or any restatement of it as a figure ("95/100", \
"confidence 95", "scored 95", "a high confidence rating").
* **Attach no such qualifier to the document-store side.** Nothing measured how sure it is, so \
any strength you gave it would be invented.
* Write it as a fact-checking note, in the same register as the answers themselves. One sentence \
to one short paragraph.

## Claim
[CLAIM]

## Question
[QUESTION]

## Answer from the document-store fact-checker
[INFACT_ANSWER]

## Answer from the internal-knowledge reasoner
[MO_ANSWER]

How sure the internal-knowledge reasoner is that its own answer is right, 0-100: [MO_CONFIDENCE]

This number tells you nothing about whether the two answers agree or conflict -- it is one side \
rating itself, and it has no counterpart on the other side. Decide `relation` without it. Use it \
only to word `merged`.

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, in exactly this shape:

```json
{
  "relation": "<agree|conflict>",
  "reason": "<one sentence>",
  "merged": "<the record entry, written as described under 'Writing the merged entry'>"
}
```
"""

# --- Self-Probing: score the answer in a SEPARATE call -------------------------------------
# Confidence used to be produced in the same generation as the answer. Measured on claim 14, that
# let the model argue in a circle: it asserted that UN officials had made public statements,
# declared `direct_recall` on the strength of its own assertion, then wrote "I recall it, so
# trace_expectation is certainly_know" and scored 0.95 -- for a claim the clean corpus could not
# support at all. Premise used to prove the premise.
#
# Xiong et al. (ICLR 2024, `MiaoXiong2320/llm-uncertainty`) measured the same failure mode at
# scale and named it: "Vanilla verbalized confidence exhibits significant overconfidence and poor
# failure prediction, casting doubts on its reliability" -- average ECE above 0.377 on weaker
# models, and even GPT-4's AUROC only 62.7%, barely above the 50% random-guess line. Their
# appendix B.3 records exactly the distribution we saw: "all the models output confidence as the
# multiples of 5, with most values ranging between the 80% to 100% range". Of their four
# strategies they report Self-Probing as the most consistent gain on the strongest model.
#
# So the score is now a second call that sees only the Question and the answer text. It cannot
# see the reasoning that produced the answer, which removes the loop by construction. The wording
# "the probability of THIS answer being correct, not the answer you would have given" is theirs,
# and is what stops the scorer from quietly substituting its own preferred answer and grading
# that instead. The scale is 0-100 integers, as in their work, not a 0-1 decimal.
#
# An earlier draft of this prompt also had the scorer emit a three-level `trace_expectation`
# label and bound each level to a score range. That defeated the point: the label decided the
# number instead of the reasoning doing it. Measured over 17 synthetic cases, all seven
# `certainly_know` rows landed in a 3-point band (95-98) -- the bucket, not a judgement. The
# label is gone; the reasoning it encoded stays, as prose.
SELF_PROBE_PROMPT = """\
# Instructions
A question was put to a reasoner working from memory alone -- no search engine, no documents. \
Below is the Question it was given and the Answer it produced. **Your task right now is to judge \
how likely that Answer is to be correct**, and nothing else.

Score the Answer you were handed. Do **not** substitute the answer you would have given and score \
that instead; if you disagree with the Answer, that disagreement is a reason to score it low, not \
a reason to rewrite it.

## When the Answer reports an absence
Many of these answers report that the reasoner found no record of something.

**Take the reasoner's report of its own memory as true.** It is not lying about what it does and \
does not recall, and "is it really true that this reasoner lacks that memory?" is not the question \
in front of you -- it is nearly always true and tells you nothing.

What you are scoring is **what that absence establishes about the Question**. An answer reporting \
an absence is making, explicitly or implicitly, a claim about the world: *there is no such thing \
to be found.* Score that claim, and the whole weight of it rests on one thing:

**If the specific fact the Question asks for were really so, would the reasoner necessarily have \
encountered it?** Apply that to the exact thing asked, not to the surrounding topic -- a famous \
event does not make every particular of it memorable. Granular administrative details (docket and \
case numbers, page counts, reference codes, precise clock times, exact addresses) sit far outside \
what a broad reasoner holds, and stay outside it even when the event they belong to is famous.

> Question: "What is the ISBN of the first edition of that biography?"
> Answer: "I have no record of the ISBN."
>
> **Wrong:** it is surely true that the reasoner has no record of it, so ~80.
> **Right:** an ISBN is exactly the sort of granular particular a broad reasoner would not hold, \
so the absence says nothing about what the ISBN is. The Answer settles nothing about the \
Question: ~15.

> Question: "In what year did the attack that toppled the Eiffel Tower occur?"
> Answer: "I have no record of any such attack; therefore it did not happen."
>
> **Right:** the absence is decisive here -- an event of that magnitude could not be missed -- so \
the claim "it did not happen" is very likely correct: ~95.

## Scoring
`confidence` is the probability, from 0 to 100, that what the Answer asserts about the Question is \
correct.

* `90-100` -- you would correct someone else with this Answer. Either the matter is firmly \
established, or the Answer reports an absence that is decisive under the test above.
* `70-89` -- the substance is very likely right, but some particular in it could be off.
* `40-69` -- the direction is probably right, the grounds are thin.
* `10-39` -- weak grounds, close to guessing, or an absence that proves nothing.
* `0-9` -- no grounds at all.

Always adhere to the following rules:
* **Use the whole range.** Do not settle on multiples of five out of habit; a score of 63 or 78 is \
perfectly acceptable and usually more honest than 60 or 80.
* An Answer that names a specific date, figure, title, or source is easier to be wrong about than \
a general one. Confident phrasing is not evidence of correctness -- judge the content.
* An Answer that admits what it does not recall and then draws a conclusion is not thereby weak. \
Score the conclusion on the test above.
* Reason concisely first, then give the number.
* Output in JSON format exactly as shown under "Output format".

## Question
[QUESTION]

## Answer
[ANSWER]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, in exactly this shape:

```json
{
  "reasoning": "<a few sentences: what the Answer claims, and what would have to be true for it \
to be right>",
  "confidence": <integer from 0 to 100>
}
```
"""

RELATIONS = ("agree", "conflict")
BASES = ("direct_recall", "inference", "no_recollection")
PREMISES = ("premise_holds", "premise_unverifiable", "premise_false")

# The sentinel recorded when InFact's stages 3&4 could not answer a question at all.
# It exists so that a retrieval failure is a *row in the table* rather than a silent
# deletion -- which is the entire methodological point of this experiment.
NONE_ANSWER = "NONE"

# What the adjudicator is shown in place of the bare sentinel. A retrieval failure IS a
# substantive report about the corpus ("nothing in here bears on this"), and the judge has to
# weigh it against whatever the reasoner remembered -- so it needs a legible sentence rather
# than a token. Only the case where BOTH sides came up empty is settled without the LLM.
NONE_DESCRIPTION = ("The document store returned no document that could answer this question; "
                    "retrieval found nothing bearing on it.")

# What the model-only side contributes when there is no score to report.
NO_CONFIDENCE = "not scored"

# --- the merged record ----------------------------------------------------------------------
# The record is rendered in the shape InFact's own procedure builds (see
# DEFAME/infact/procedure/variants/qa_based/base.py: "### {question}\nAnswer: ...\n\nSource URL:
# ..."), so the verdict stage reads something structurally identical to what it normally gets.
#
# The header is where the verdict stage is told that a CONFLICT is not two pieces of evidence.
# InFact's judge prompt instructs it to "use information only from the recorded evidence" and
# gives it no notion of evidence being wrong, so left to itself it will summarise both sides of a
# conflict as jointly established and average them into an uncertain verdict. At least one of the
# two IS wrong; the judge has to pick.
MERGED_RECORD_HEADER = """\
## Merged Q&A

Each question below was answered twice: once from the retrieved document store, and once by a \
reasoner working from memory alone, with no access to any document. Where the two agreed, their \
answers are combined into one. Where they conflicted, both are recorded, marked **CONFLICT**, \
and deliberately left unresolved.

**A CONFLICT means at least one of the two is wrong.** Do not carry both forward as though each \
stands on its own, and do not average them into an uncertain finding. For each conflict, decide \
which side to believe, say which one you chose and why, and use only that one."""

# The header InFact's own procedure writes (base.py:38). Used verbatim by the baseline arms so
# their record is indistinguishable from what the fact-checker normally hands its judge.
INFACT_NATIVE_HEADER = "## Initial Q&A"

# Templates for the two row types that never reach the LLM.
MERGED_BOTH_EMPTY = ("Neither the document store nor the reasoner's memory has anything bearing "
                     "on this question.")
MERGED_MO_FAILED = ("Only the document store answered this question; the memory-only reasoner "
                    "produced no usable answer. From the document store: {infact_answer}")

NO_URL = "none -- retrieval returned no document"


# --- what the verdict stage is told about a two-source record --------------------------------
# Goes into judge.md's [EXTRA_RULES] slot (judge.md:11, wired through Judge(extra_rules=...) in
# DEFAME/infact/modules/judge.py:27). Under the binary label space that slot is empty
# (AVeriTeCBinary.extra_judge_rules is None), so nothing is overwritten.
#
# Two things in judge.md make this necessary. Its step 1 says "Focus on the findings from the
# retrieved evidence" -- half of a merged record is not retrieved, and that instruction tilts the
# judge towards the document store, which is backwards for this design. And its rule "Use
# information only from the recorded evidence" frames everything inside "# Record" as material to
# be weighed, so the CONFLICT instruction in MERGED_RECORD_HEADER risks being read as something
# to evaluate rather than something to obey. It is repeated here, in the instruction section,
# where the judge's other rules live.
#
# The baseline arms must NOT receive this. A baseline that has been given our rules is not a
# baseline.
JUDGE_EXTRA_RULES = """\
* **The Record contains answers from two independent sources**: a document store, and a reasoner \
working from memory alone with no access to any document. Both are evidence and both are part of \
the recorded fact-check. Do not discount the memory-only findings for carrying no URL, and do not \
mistake them for your own prior knowledge.
* **Where an answer is marked CONFLICT, the two sources are irreconcilable and at least one of \
them is wrong.** Do not carry both forward as though each stands, and do not average them into an \
uncertain finding. Decide which side to believe, say which one you chose and why, and use only \
that one.
* **Neither source is right by virtue of what it is.** A document is not correct merely because \
it was retrieved, and a recollection is not correct merely because it is held with confidence."""


def render_record(rows, header: str = MERGED_RECORD_HEADER, mark_conflicts: bool = True) -> str:
    """Render rows into the record shape InFact's own procedure builds.

    Mirrors DEFAME/infact/procedure/variants/qa_based/base.py:35-38 so the verdict stage reads
    something structurally identical to what it normally gets. `header` and the CONFLICT marker
    are the only departures, and both are switched off for the baseline arms.

    Each row needs `question`, `infact_url`, one of `merged`/`infact_answer`, and -- when
    marking conflicts -- `relation`.
    """
    parts = [header]
    for r in rows:
        mark = "**CONFLICT.** " if mark_conflicts and r.get("relation") == "conflict" else ""
        answer = r.get("merged") or r.get("infact_answer")
        parts.append(f"### {r['question']}\n"
                     f"Answer: {mark}{answer}\n\n"
                     f"Source URL: {r.get('infact_url') or NO_URL}")
    return "\n\n".join(parts)


def valid_mo(d) -> bool:
    return isinstance(d.get("answer"), str) and d.get("answer_basis") in BASES


def valid_probe(d) -> bool:
    conf = d.get("confidence")
    # The score is the whole point of this call, so a missing or out-of-range value is a parse
    # failure rather than something to paper over.
    return (isinstance(conf, (int, float)) and not isinstance(conf, bool)
            and 0 <= conf <= 100)


def valid_adj(d) -> bool:
    # `merged` is what the verdict stage actually reads, so an empty one is a parse failure
    # rather than a row to carry forward with a hole in it.
    merged = d.get("merged")
    return (d.get("relation") in RELATIONS
            and isinstance(merged, str) and bool(merged.strip()))
