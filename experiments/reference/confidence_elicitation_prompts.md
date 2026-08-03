# Reference: confidence-elicitation prompts from prior work

Extracted verbatim from **MiaoXiong2320/llm-uncertainty** (Xiong et al., *Can LLMs Express Their
Uncertainty? An Empirical Evaluation of Confidence Elicitation in LLMs*, ICLR 2024) so we do not
have to keep the repo. The clone was deleted after extraction.

**No LICENSE file in that repo** — the README only asks that the paper be cited. So treat these as
reference material to learn from, not code to vendor. If any wording ends up close to theirs in a
published prompt, cite the paper.

Their headline finding matches what we measured on claim 14: *"LLMs, when verbalizing their
confidence, tend to be overconfident, potentially imitating human patterns"*, and human-inspired
prompting mitigates it *"with diminishing returns in advanced models"*.

---

## 1. Vanilla / CoT — the plain verbalized score

```
Read the question, analyze step by step, provide your answer and your confidence in this answer.
Note: The confidence indicates how likely you think your answer is true.
Use the following format to answer:
```Explanation: [insert step-by-step analysis here]
Answer and Confidence (0-100): [ONLY the {answer_type}; not a complete sentence], [Your confidence
level, please only include the numerical number in the range of 0-100]%
```
Only give me the reply according to this format, don't give me any other words.
```

Two details worth copying:
* **"The confidence indicates how likely you think your answer is true"** — the plain
  probability wording. The companion paper (*On Verbalized Confidence Scores for LLMs*) found
  this single change (`probscore`) was the largest improvement for smaller models.
* **0-100 integers, not a 0-1 decimal.**

## 2. Top-K — k guesses, each with its own probability

```
Provide your {k} best guesses and the probability that each is correct (0% to 100%) for the
following question. Give your step-by-step reasoning in a few words first and then give the final
answer using the following format:
G1: <ONLY the {answer_type} of first most likely guess; not a complete sentence, just the guess!>
P1: <ONLY the probability that G1 is correct, without any extra commentary whatsoever; just the
probability!>
...
Gk: <ONLY the {answer_type} of k-th most likely guess>
Pk: <ONLY the probability that Gk is correct, ...>
```

Implementation note in their code: `confidence_before_all_answers = True`, with the comment
*"we finally use the confidence before all answers prompting"* — each `P` immediately follows its
own `G` rather than listing all guesses then all probabilities. They settled on that ordering.

## 3. Self-Probing — score the answer in a SEPARATE call

```
Question: {question_text}
Possible Answer: {answer}
Q: How likely is the above answer to be correct? Please first show your reasoning concisely and
then answer with the following format:
```Confidence: [the probability of answer {answer} to be correct, not the one you think correct,
please only include the numerical number]%```
```

The load-bearing clause is **"not the one you think correct"**: it forces the model to score the
answer it was handed instead of quietly substituting its own preferred answer.

---

## What transfers to us, and what does not

**Transfers:** all three prompt shapes, the probability wording, the 0-100 scale.

**Does not transfer:** their evaluation. Their tasks are multiple-choice and numeric QA with a
known correct answer, so they can compute ECE / AUROC against correctness. Our sub-question
answers are open-ended free text with no per-answer ground truth, so we cannot score calibration
the same way. Their *prompts* are usable; their *metrics* are not.

**Most relevant to our open problem** (`MO_ANSWER_PROMPT` scoring its own answer in the same
generation, which on claim 14 let it argue "I recall it, therefore `certainly_know`" — circular):
Self-Probing splits generation from scoring into two calls, which removes that loop by
construction. Top-K attacks the same overconfidence from the other side by forcing the model to
name alternatives before committing.
