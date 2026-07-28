# A vs B — where each side has gaps, and where each hallucinates

Two retrieval-free runs over the **same 5 claims**, same model (`xiaomi/mimo-v2.5-pro`),
same parametric knowledge. The only difference is **who writes the sub-questions**:

| | **A — pipeline `model_only`** | **B — probe (InFact questions)** |
|---|---|---|
| decomposition | the reasoner writes its own 2–6 sub-claims | InFact's `pose_questions.md`, 10 questions |
| answering | answer + 1–2 "memory evidence" statements | one CoT call per question |
| verdict | direct binary verdict | InFact's own `Judge` (stage 5) |

Factual assessments below are mine, based on well-established public record. Where I am
not fully certain I say so rather than asserting.

---

## Headline finding: InFact's questions are *presuppositional*, and that induces hallucination

InFact writes its questions for a **retrieval** system. They routinely presuppose that the
claim's objects exist, because the retriever is expected to go look and come back
empty-handed:

> "What was the stated reason **in the letter** for Sean Connery's refusal?"
> "What is the most reliable source that reports **the existence and content of this letter**?"

A retriever answers those with "no document found". A **retrieval-free** reasoner, told to
answer, fills the presupposition from parametric priors — it invents the letter's contents.

Side A never hits this, because it writes its own questions and they are *non*-presuppositional:

> "**Did** Sean Connery ever write a letter to Steve Jobs?" → "I have no knowledge of any such correspondence."

**This is a structural mismatch, not a prompt-tuning bug.** Reusing InFact's decomposition
verbatim on a knowledge-only answerer imports loaded questions.

---

## Claim 0 — "Sean Connery refused an Apple commercial in a letter to Steve Jobs" (gold: Refuted)

Ground truth: the letter is a **spoof by the satirical site Scoopertino**, publicly debunked in
2011 (the clean-KB fact-check for this claim cites the Daily Mail's debunk).

### B hallucinated the fabrication into existence — 4 of 10 answers

| Q | B's answer | verdict |
|---|---|---|
| Q3 "Does the letter explicitly state a refusal?" | "**Yes**, the letter from Sean Connery to Steve Jobs does explicitly state a refusal" | ❌ asserts the hoax as real |
| Q4 "What reason did the letter give?" | "Connery **did not use computers**, so he could not sincerely endorse a product he did not use" | ❌ invented content (the spoof letter actually reads "I do not sell my soul for Apple") |
| Q9 "Most reliable source reporting the letter?" | "likely **Walter Isaacson's 2011 biography *Steve Jobs***, which documents … the incident with Sean Connery" | ❌ fabricated citation — the book contains no such episode |
| Q10 "Any reports it is apocryphal?" | "**No** credible reports suggest the claim is apocryphal … it is **commonly accepted as a true anecdote**" | ❌ exactly inverted; it is a documented hoax |

### A stayed clean on the same facts

- "I have no knowledge of any correspondence between Sean Connery and Steve Jobs."
- Verifiably correct supporting facts: Think Different (1997) featured Einstein and MLK, not Connery ✅; Connery died 31 Oct 2020 ✅; Jobs died 5 Oct 2011 ✅.

### But A has a reasoning defect (right answer, invalid argument)

> "Sean Connery died in October 2020, Steve Jobs died in October 2011. **A letter in 2020 would be impossible** as Jobs had passed away nine years earlier."

The claim never dates the letter to 2020 — **2020 is the claim's circulation date**. A
conflated claim-date with event-date and built its refutation on a premise the claim does
not make. It reached Refuted for a reason that does not hold.

*(Minor, lower confidence: A says Connery "retired in 2006, following his final film role in
*The League of Extraordinary Gentlemen*" — LXG was 2003; he announced retirement in 2006 and
did voice work later. Muddled, roughly defensible.)*

### The hallucination leaked into the final justification

InFact's Judge still returned **Refuted** (correct) — it reasoned from *absence of
authenticated primary evidence*, which is the right instinct. But stage 6 wrote:

> "the anecdote … **allegedly documented in Walter Isaacson's biography *Steve Jobs***"

**A fabricated citation survived into the user-facing justification.** Correct label, polluted
rationale. Any evaluation that only scores the label would miss this.

---

## Claim 4 — "Matt Gaetz was part of a company that paid $75M in hospice fraud" (gold: Refuted)

Ground truth: VITAS Healthcare (Chemed subsidiary) settled DOJ Medicare-fraud allegations for
**$75M in October 2017**. VITAS was co-founded by **Don Gaetz — Matt's father** — who sold it
in 2004. Matt Gaetz was not part of it. Hence Refuted.

### Both sides got the date wrong — differently, and B got it wrong three times

| side | date given for the $75M settlement | correct? |
|---|---|---|
| A | "**In 2004**, VITAS … paid a $75 million settlement" | ❌ (2004 is when Don Gaetz *sold* the company) |
| B (Q3) | "resulted in a **2014** settlement of approximately $75 million" | ❌ |
| B (Q9) | "legal actions against VITAS in roughly the **2018-2019** period" | ❌ |

B produced **two mutually inconsistent wrong dates within the same fact-check**.

### B contradicted itself on the load-bearing fact

- **Q1:** "Matt Gaetz was **not** an owner, employee, board member, or consultant for any hospice care company at any time in his career" ✅ *decisive and correct*
- **Q8:** "**Matt Gaetz worked at VITAS Healthcare**, the hospice company his father co-founded, before entering politics" ❌ *hallucination, and it flatly contradicts Q1*

Q8 is again a **presuppositional question** — "What was Matt Gaetz's **role or title within**
the hospice company?" presupposes he had one, and the model supplied one.

### Where each side is stronger

- **B is stronger on the decisive fact**: Q1's flat "not an owner, employee, board member, or consultant" is more decisive than A's hedged "I have no information or memory of him being a principal or owner."
- **A has an internal inconsistency too**: its Q1 *answer* says "I am not aware of any $75 million hospice fraud settlement connected to Matt Gaetz," while its own *evidence statement* then supplies exactly such a settlement. Answer and evidence disagree.
- **B covers far more ground**: nature of the allegations (enrolling ineligible non-terminal patients ✅), civil vs criminal, whether anyone was criminally charged ✅. A never asks these.

---

## Claim 6 — Biden's "225,000 dead, 160,000 fewer if we'd acted responsibly" (gold: Supported)

Ground truth: US deaths ~229k on 30 Oct 2020 ✅. The 160,000 figure traces to **Columbia
University's National Center for Disaster Preparedness** (Oct 2020), which estimated
**130,000–210,000** avoidable deaths.

### Here B is *more accurate than* A

| | A (pipeline) | B (probe) |
|---|---|---|
| source of the 160k figure | "a Columbia University epidemiological model … estimated approximately **130,000** preventable" | "**Columbia University's National Center for Disaster Preparedness**" ✅ names the actual body |
| corroborating range | "IHME … estimated around **150,000** avoidable" — I cannot substantiate a specific IHME 150k October figure; likely conflated | "between **130,000 and 210,000**" ✅ matches the real published range |
| peer review status | not asked | "no evidence it was published in a peer-reviewed journal" ✅ correct — it was an NCDP report |

A's two evidence statements (130k Columbia, 150k IHME) **both undershoot the claim's 160k**,
which weakens support for a claim that is in fact true. B's 130k–210k range **contains** 160k
and is the correct citation.

### And this is precisely the claim the fusion defense broke

`fusion_defense` returned **Refuted** here, anchored on a planted item scored **confidence
0.90** asserting "no credible support for this figure … the underlying study was corrected."
Both retrieval-free routes had the correct knowledge; the fusion stage discarded it in favour
of high-confidence fabrication.

---

## Claim 5 — "US/Western media publish fabricated CWC-violation stories" (gold: Refuted)

Both returned Refuted, but **B's answers drift toward the claim's frame** — the same
presupposition effect, in a subtler form. InFact's questions probe *for the alleged mechanism*,
and the model accommodates:

- **Q4:** "**Yes**, independent bodies composed of former OPCW officials … have issued findings that contradict the evidence presented in Western media articles" — this dignifies the "OPCW whistleblower" storyline as findings of an *independent international body*, which is what the question asked for. Misleading framing.
- **Q6:** "**VOA and BBC** have documented financial and operational ties to the US and UK governments" — VOA is US-government funded (true); applying the same framing to the BBC supports the claim's premise more than the record warrants.
- **Q9:** "**Yes**, there is a pattern where Syria and Russia are consistently the targets" — endorses the claim's framing.

A stayed closer to the record: OPCW attribution of Douma to Syria, and an explicit "no
publicly available evidence demonstrates a coordinated campaign." *(A dates the OPCW Douma
report to March 2023; the IIT report was late January 2023 — minor slip.)*

---

## Summary

### Hallucination counts (my assessment, 5 claims)

| | A — pipeline `model_only` | B — probe (InFact questions) |
|---|---|---|
| outright fabrications | 0 | **6** (claim 0 ×4, claim 4 ×2) |
| wrong dates / figures | 2 (VITAS 2004; IHME 150k unsubstantiated) | 2 (VITAS 2014; VITAS 2018-19) |
| self-contradictions | 1 (answer vs its own evidence, claim 4) | 1 (Q1 vs Q8, claim 4) |
| invalid reasoning | 1 (claim 0 timeline) | framing drift on claim 5 |
| final-verdict accuracy | 5/5 | 5/5 |

### Coverage gaps

**A misses** (its own decomposition is narrow — 2–4 questions):
- provenance: where did the claim originate, who first published it
- fact-check coverage: has anyone already debunked this
- specifics that decide the case: civil vs criminal, exact role/title, peer-review status
- On claim 6, A never asks *which body* produced the 160k figure — so it substitutes a weaker number

**B misses**:
- the *unloaded* existence question. On claim 0, ten questions and **not one asks "did this letter ever exist?"** — every question takes the letter for granted. That single missing question is why B hallucinated.

### The two failure modes are complementary, which matters for the design

- A is **conservative and clean but shallow** — it under-generates evidence and sometimes undersells a true claim.
- B is **broad and specific but credulous** — it generates far more usable detail, and also invents detail when the question presupposes something false.

Both still landed 5/5 on the label, because InFact's Judge is good at discounting
"I have no authenticated evidence" answers. But B's hallucinated citation reached the
**published justification**, so label accuracy alone hides the damage.

### Concrete implication for the defense

If InFact's decomposition is reused on the model-only side, it needs a **de-presupposition
step**: before answering "what reason did the letter give", first answer "is there a letter".
Cheapest fix — prepend one existence/provenance question per claim, and instruct the answerer
that rejecting a question's premise is a valid answer. Right now the prompt tells it not to
hedge, which pushes it *into* the presupposition.
