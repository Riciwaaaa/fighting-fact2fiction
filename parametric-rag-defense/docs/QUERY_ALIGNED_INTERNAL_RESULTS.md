# Query-aligned internal-knowledge results

Status: complete method-development experiment. The previously selected low-rate corroboration
method remains the primary candidate. The localized extension described below was designed after
examining development errors and therefore requires fresh confirmation.

## Plain-language conclusion

The experiment supports a narrower claim than “ask the model every RAG subquestion and trust its
memory.” Internal answers to the exact questions asked by RAG are useful for identifying suspicious
parts of a failed RAG trace, but they are not reliable enough to replace either the full-claim
closed-book answer or the existing defense.

The strongest observations are:

1. When the same model gives two stable closed-book answers to an exact RAG question and those
   answers contradict the RAG answer, the final RAG verdict is much more likely to be wrong.
2. Treating every such contradiction as poison and deleting all associated evidence makes accuracy
   substantially worse. Internal knowledge and semantic comparison are both noisy.
3. Requiring the deletion to change the RAG verdict removes some false alarms, but still produces
   three corrections and four regressions relative to the selected method.
4. In retrospective development analysis, corrections occur when conflict is repeated but
   localized: at least two of the ten questions conflict, but no more than one third of the stable
   internal answers conflict. This rule produces three corrections and no regressions, but those
   corrections come from only two distinct claims. Its claim-clustered 95% interval includes zero.

The full-claim three-call answerability signal should therefore remain the backbone. Query-aligned
internal knowledge is a possible conservative diagnostic layer, not a replacement for it.

## Experiment

The source contains 363 clean or low-rate rows where same-model RAG and the same model's three-call
closed-book majority disagree. There are 159 unique model/claim question plans because the clean
and poisoned conditions often reuse the same ten generated questions.

For each plan:

1. The same victim model answered the exact ten RAG-generated questions twice without retrieval.
   It saw only each question and the claim date.
2. The same model compared the two internal answers with the original RAG answer. It did not see
   passages, endpoint verdicts, poisoning rate, provenance, or gold.
3. A question was eligible only if the two internal attempts were semantically stable, contradicted
   the RAG answer, and the RAG answer had selected a passage.
4. For every conflict-flagged row, all eligible selected document identities were removed globally
   from the ten already retrieved groups. There was no new retrieval and no backfill.
5. The unchanged RAG answer and final-verdict prompts were rerun with the same victim model and the
   original ten-question plan.

This is a fixed-context causal intervention: it tests whether removing the suspected input changes
the downstream verdict. Poison provenance is joined only after all model outputs are immutable.

## Does question-level internal conflict identify risk?

Yes, as a diagnostic. On the 263 attacked endpoint disagreements, 129 rows were conflict-flagged.
RAG was wrong on 97/129 flagged rows (75.2%) and 52/134 unflagged rows (38.8%), a 1.94 risk ratio.
At least one actually poisoned document was among the suspects on 89/129 flagged rows (69.0%). The
flag recalled 89/164 rows where poison had been selected into the final RAG record (54.3%).

The behavior is strongly model-dependent:

| Victim | Attacked rows | Flagged | RAG wrong if flagged | RAG wrong if unflagged | Reading |
|---|---:|---:|---:|---:|---|
| GLM 5.2 | 89 | 63 | 58/63 | 11/26 | Strong diagnostic |
| Llama 3.1 70B | 95 | 11 | 3/11 | 31/84 | Signal is sparse and inversely useful |
| Qwen 3.5 35B-A3B | 79 | 55 | 36/55 | 10/24 | Useful but noisy |

This heterogeneity is important. The exact-question replay cannot be presented as a universally
reliable detector. Llama frequently declines or fails to produce two stable question-level answers,
and the few conflicts it does flag are not enriched for RAG errors.

## Does removing suspected evidence improve predictions?

Not by itself. The table below reports accuracy only on the 363 endpoint-disagreement rows, where
the intervention can matter.

| Policy | Correct | Paired change versus selected corroboration |
|---|---:|---:|
| Selected corroboration baseline | 293/363 | — |
| Replace on every conflict-flagged rerun | 248/363 | Large loss |
| Replace only when removal changes RAG | 292/363 | 3 gains, 4 regressions |
| Repeated-and-localized conflict plus verdict change | 296/363 | 3 gains, 0 regressions |

Private post-output analysis explains the asymmetry. When the intervention removed an actually
poisoned document and changed the verdict, it yielded two gains and no regressions. When it removed
only clean documents, it yielded one gain and four regressions. Provenance cannot be used at
inference, so “remove poison” is not an implementable rule. The localized pattern is an observable
surrogate discovered from these development errors.

The development-only localized rule requires:

- at least two eligible question conflicts;
- eligible conflicts on no more than one third of stable internal question answers; and
- a fixed-context rerun verdict different from the original RAG verdict.

This encodes a defensible hypothesis: one conflict is likely comparison noise, while broad conflict
suggests general endpoint disagreement or excessive context removal rather than one localized
corruption. A small, repeated cluster of contradictions is the setting in which internal knowledge
can identify and causally test a suspect part of the retrieved context.

## Projected full-system performance

The following figures apply the post-tuned localized rule to the prior selected same-model
corroboration method. They are not held-out confirmation.

| Condition | RAG | Model-only | Three-call answerability | Selected corroboration | Localized extension |
|---|---:|---:|---:|---:|---:|
| Clean | 227/300 | 207/300 | 237/300 | 244/300 | 244/300 |
| 0.1% | 182/227 | 175/227 | 200/227 | 208/227 | 209/227 |
| 0.25% | 177/227 | 175/227 | 200/227 | 210/227 | 211/227 |
| 0.5% | 151/227 | 175/227 | 195/227 | 202/227 | 203/227 |

The three attacked row-level gains are only two independent claim-level events: one GLM claim is
corrected at both 0.1% and 0.25%, and one Qwen claim is corrected at 0.5%. Llama receives no gain.
The claim-clustered 95% bootstrap interval for disagreement-row accuracy difference is
`[0.0, 0.0314]`. The lower bound of zero and the post-label threshold selection prevent a positive
generalization claim.

For a purer internal-knowledge-centered variant, the same localized intervention can sit directly
on the three-call answerability backbone. Its projected totals are 237/300 clean and 201/227,
201/227, and 195/227 under the three attack rates. This beats both raw endpoints at each attacked
rate, but improves the answerability backbone by only one case at 0.1% and 0.25% and none at 0.5%.

## What should be claimed in a paper

The defensible workshop-level story is not that question-level memory solves poisoning. It is:

- repeated full-claim internal answers provide the main selective fallback;
- exact-question internal replay exposes conflict at the interface where retrieval changes the
  model's answer;
- a fixed-context removal test distinguishes mere disagreement from downstream influence; and
- internal conflict must be treated as a selective, model-dependent signal because unconditional
  intervention is harmful.

The current data support the first three as mechanistic observations. They do not yet confirm that
the localized extension improves the already selected method on new claims.

## Required next experiment

Freeze the current prompts, two replay seeds, comparator, document-removal semantics, and localized
thresholds. Evaluate once on claims not used anywhere in this method-development cycle. Report the
answerability backbone and the selected corroboration backbone separately, cluster uncertainty by
claim, and require positive net gains for at least two victim models. If the rule does not transfer,
retain the query-aligned analysis as a negative/mechanistic ablation and keep the prior method.

## Reproducibility

Completed outputs:

- 318/318 closed-book question-replay outputs (159 cases, two seeds);
- 304/304 unique semantic-comparison packets, expanded deterministically to 363 rows;
- 165/165 fixed-context answer reruns and 165/165 final-verdict reruns;
- zero unresolved failures and zero new retrieval calls in the intervention.

Machine-readable results are retained at:

- `artifacts/evaluation/query_aligned_conflict_map_v1.json`;
- `artifacts/evaluation/query_aligned_intervention_v1.json`;
- `artifacts/runs/query_aligned/query_aligned_internal_replay_v1/`;
- `artifacts/runs/query_aligned/query_aligned_conflict_map_v1/`; and
- `artifacts/runs/query_aligned/query_aligned_intervention_v1/`.

Regenerate the two evaluation summaries without provider calls:

```bash
.venv/bin/python scripts/summarize_query_aligned_conflict.py
.venv/bin/python scripts/summarize_query_aligned_intervention.py
```

The frozen development candidate and its provenance warning are in
`configs/query_aligned_localized_candidate_v1.json`.
