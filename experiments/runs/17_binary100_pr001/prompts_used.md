# Pass E prompt — `--conf-rules v2`

Model: `xiaomi/mimo-v2.5-pro`. Written by `exp06_adjudicate.py` at run time; this is the exact template, before per-row substitution.

## ADJUDICATE_MERGE_PROMPT

```
# Instructions
Two independent fact-checkers answered the same Question about a Claim. One had access to a document store; the other answered from internal knowledge alone. You have two tasks:

1. **Decide whether their two answers agree or conflict.** Do not decide who is right, do not fact-check the Claim yourself, and do not reason about what the answers imply for the Claim's final verdict.
2. **Write the single record entry that a later stage will read in place of both answers.**

## The deciding test
**Is the information in the two answers compatible, or not?**

* `agree`: the two answers convey compatible information. Either they say substantively the same thing, or what each says leaves the other intact.
* `conflict`: they are not compatible -- they cannot both be true, or one holds information that the other's answer contradicts or fails to support.

## What the two answerers are, and how that changes the standard
The document-store answerer works **open-book**: it quotes sources and can be exact about dates, figures, names, and attributions. The internal-knowledge answerer works **closed-book**: it answers from memory, so it is legitimately vaguer, more hedged, and less precise. **Do not hold them to one standard of precision.** A closed-book answer is not in conflict merely for being less certain or less specific than an open-book one.

## Rules
* You must choose one of the two labels. There is no "cannot compare" option: this is a forced binary judgement.
* **Same substance, different certainty or precision, is `agree`.** One answer confident and the other hedged, one giving an exact value and the other a looser value that contains it, or one supplying an identifier the other cannot recall -- all `agree`, provided the substance matches.
* **"I have no knowledge of X" and "there is no record of X" are substantive negative answers**, not refusals to answer. The reasoner is reporting that X is not attested anywhere in a broad body of knowledge. Compare it on that basis, and never set the pair aside for it.
* **One side holding information the other lacks is a `conflict`**, whichever side holds it: one answer establishing something the other has no trace of, or one answer asserting a fact the other's sources could not support.
* Opposite yes/no answers on the load-bearing point, or incompatible facts, figures, dates, locations, or attributions, are `conflict` even if the rest agrees.
* Judge only the substance of the two answers as given. Do not use outside knowledge to decide which is correct.
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
> A: "There is documented evidence of correspondence between them: a verified scanned copy of Connery's 2011 letter to Jobs."
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
`merged` replaces both answers in the record that the verdict stage reads. That stage never sees this Question answered twice, never sees the two answers separately, and never sees the label you just chose -- it sees only what you write here. Anything you leave out is gone.

* When the two **agree**: state the shared finding once. Two things must survive that compression:
  * **Whatever only one side had, say which side had it.** Where one answer supplied a particular the other did not -- a figure, a date, a document or reference number, a named official, an outcome, an attribution -- keep it, and name its source ("the retrieved document adds ...", "the reasoner recalls ..."). Only what **both** answers actually attest may be stated flatly, with no source named. An `agree` label means the two are compatible; it does not mean they said the same things, and a particular that came from one side must not be written as though both had it.
  * **Never delete a report of absence.** If the memory-only side reported that it has no record of something, that report stays in the entry, even though you judged the two compatible. It is a finding about a broad body of knowledge, not an empty answer, and dropping it is the one thing you must not do here.
* When the two **conflict**: give **both positions, each attributed to its source** -- "the retrieved document states ...", "the reasoner working from memory alone reports ...". Then stop. **Do not resolve it, do not hint at which is more likely, do not split the difference.** Choosing between them is the next stage's job, not yours.
* **Keep the substance on both sides.** If the memory-only answer supplies a competing account -- that the event never happened, that it was someone else, that it was a different year -- that account goes into the merged entry in full. "The two sides disagree" is not an acceptable merged entry; it tells the next stage nothing it can act on.
* **Say how far the memory-only finding reaches**, in a conflict and equally in an `agree` entry that carries a report of absence. The number given below rates **what that side's answer establishes about this Question** -- not how careful, competent, or trustworthy the reasoner is. It runs high when the answer would be hard to be wrong about: a matter so public that a broad reasoner could not have missed it, or something it plainly remembers. It runs low when the Question turns on a particular that no broad reasoner would hold either way -- a document or reference number, an exact address, a precise time, an internal record -- so that side's answer, whichever way it goes, leaves this Question open. Write that reach into the finding itself:
  * Near the top: *"the reasoner has no record of any such attack, and an event of that scale could not have escaped it, so it reports that it never happened."*
  * Near the bottom: *"the reasoner has no record of the document's reference number, though a particular of that kind would not be in its knowledge either way."*
  * **Never describe the reasoner's state in place of the finding's reach.** Not "is close to guessing", not "is not very confident", not "is uncertain", "is tentative", "is unsure", "has low confidence". Those are read downstream as a verdict on the source, and no such verdict was ever measured -- what was measured is how much this one answer settles this one Question.
  * **Never write the number itself**, or any restatement of it as a figure ("95/100", "confidence 95", "scored 95", "a high confidence rating").
* **Neither side may be described as the more reliable one.** Nothing measured how sure the document store is, and the number below is not a rating of the reasoner, so any comparison of the two sources' standing would be invented. Report what each one found. How far a finding reaches is the only strength language permitted, and only the memory-only side has it, because only there was it measured.
* Write it as a fact-checking note, in the same register as the answers themselves. One sentence to one short paragraph.

## Claim
[CLAIM]

## Question
[QUESTION]

## Answer from the document-store fact-checker
[INFACT_ANSWER]

## Answer from the internal-knowledge reasoner
[MO_ANSWER]

How much the internal-knowledge reasoner's answer settles about this Question, 0-100: [MO_CONFIDENCE]

This was rated by a separate step that saw only the Question and that one answer. It is a statement about the answer's reach on this Question, not about the reasoner's general standing, and it has no counterpart on the document-store side. It tells you nothing about whether the two answers agree or conflict -- decide `relation` without it. Use it only to word `merged`.

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, in exactly this shape:

```json
{
  "relation": "<agree|conflict>",
  "reason": "<one sentence>",
  "merged": "<the record entry, written as described under 'Writing the merged entry'>"
}
```

```
