# Fresh confirmation execution log

This is the human-readable progress companion to the immutable manifests and progress ledgers
under `artifacts/runs/environment_confirmation_train_v1/`.

## 2026-08-12 — Scope and protocol frozen

- Audited a 100-claim AVeriTeC train split: 50 Supported, 50 Refuted, 100 unique claim/date
  prompts, and zero exact prompt overlap with all of AVeriTeC dev.
- Isolated confirmation calls in `artifacts/cache/llm_environment_confirmation_train_v1/`.
- Froze the same-model rate matrix, fixed development clean references, inference restrictions,
  baselines, online evaluation, and success gate in
  `configs/environment_confirmation_protocol_v1.json` before any confirmation model call.
- Commit before inference: `ccd69bb`.

## 2026-08-12 — Knowledge store prepared

- Downloaded the official AVeriTeC `train_0_999.zip` knowledge shard.
- Verified size: 20,730,339,734 bytes.
- Local archive SHA-256:
  `389d2284c5f25410205ec530c2101c3e6d575eae460731e1909ad19192dcb810`.
- Extracted and verified all 100 selected per-claim knowledge files. Index construction uses the
  pinned Fact2Fiction embedding model and is resumable per claim.

## 2026-08-12 — Closed-book endpoint complete

- Collected and cached 900/900 calls: three seeds for every model/claim pair.
- Completeness and artifact audits pass for all three models; no provider-call or accepted-output
  contract failures occurred.
- One Qwen attempt failed only the response-format contract; its repair call and invalid attempt
  are both retained. GLM and Llama needed no repair calls.
- Referenced token totals: GLM 190,810; Llama 175,596; Qwen 221,161; total 587,567.
- Gold was joined only after collection and audit. Three-call majority accuracy on the 100 fresh
  claims is GLM 72%, Llama 60%, and Qwen 74%.

## 2026-08-12 — Interruption checkpoint

The server interruption did not corrupt the experiment. No collection or indexing process remains
active. All completed work is stored in per-call caches or per-claim artifacts and can be resumed
without repeating successful calls.

### Durable state

- Git branch `main` is clean. The confirmation protocol remains frozen at commit `ccd69bb`; the
  latest recorded-work commit before this checkpoint is `74b528b`.
- Knowledge archive and all 100 selected raw resources are present. Retrieval indexes exist for
  85/100 claims. Index construction is atomic per claim, so resumption will skip those 85 indexes.
- Closed-book collection is complete: 900/900 accepted outputs, covering 100 claims, three models,
  and three calls per model/claim. The audit and gold-joined summary are present.
- A diagnostic prefix scan was completed while indexing was in progress. It covers the first 36
  indexed claims: 108 clean endpoints and 430 attacked endpoints (86 clean-correct model/claim
  pairs times five attack rates), with zero unresolved failures. These endpoints are cached and
  will be reused by the full run.
- The diagnostic prefix is **not** the confirmation result: the 36 claims were determined by index
  availability, and the clean eligibility manifests will be regenerated over all 100 claims.
- The isolated confirmation LLM cache currently contains 2,144 attempt records. The raw/extracted
  data occupy about 26 GiB; the run artifacts occupy about 50 MiB.

The non-final prefix scan already confirms that the attack is effective, but it must not be used
to accept or revise the frozen method. Its clean-correct counts are GLM 32/36, Llama 28/36, and
Qwen 26/36. Attacked RAG accuracy from 0.1% through 8% was respectively: GLM 71.9%, 56.3%, 25.0%,
9.4%, 3.1%; Llama 96.4%, 89.3%, 71.4%, 32.1%, 28.6%; and Qwen 69.2%, 57.7%, 23.1%, 7.7%, 11.5%.

### Exact continuation order

Run from the repository root with the existing virtual environment and credentials. Every command
is resumable and reuses the isolated confirmation cache.

1. Finish the remaining 15 retrieval indexes:

   ```bash
   PYTHONPATH=src .venv/bin/python scripts/prepare_stage1_kb.py \
     --config configs/stage1_environment_confirmation_train_v1.json \
     --archive artifacts/data/averitec_train_confirmation/train_0_999.zip \
     --index-only --device cuda:0 --batch-size 64
   ```

2. Re-enter the clean scan over the complete 100-claim split. The 108 cached prefix endpoints will
   be reused, and the final run will regenerate full clean manifests and victim-specific
   Fact2Fiction eligibility sets:

   ```bash
   PYTHONPATH=src .venv/bin/python scripts/run_stage1_rag_scan.py \
     --config configs/stage1_environment_confirmation_train_v1.json \
     --phase clean --tier fresh_confirmation_curve --workers 6 \
     --contract-retries 5 --device cuda:0 \
     --experiment-id environment_confirmation_clean_v1
   ```

3. Run the complete same-model attacked scan. Existing prefix poison corpora and endpoints will be
   reused; new work is generated only for newly eligible pairs:

   ```bash
   PYTHONPATH=src .venv/bin/python scripts/run_stage1_rag_scan.py \
     --config configs/stage1_environment_confirmation_train_v1.json \
     --phase poison --tier fresh_confirmation_curve --workers 6 \
     --contract-retries 5 --device cuda:0 \
     --experiment-id environment_confirmation_diagonal_v1
   ```

4. Summarize raw endpoints, then collect and audit the original-view evidence reports for every
   RAG/internal disagreement:

   ```bash
   PYTHONPATH=src:scripts .venv/bin/python scripts/summarize_environment_confirmation_endpoints.py \
     --config configs/stage1_environment_confirmation_train_v1.json

   PYTHONPATH=src:scripts .venv/bin/python scripts/run_evidence_signal.py \
     --config configs/stage1_environment_confirmation_train_v1.json \
     --experiment-id environment_confirmation_evidence_v1 \
     --conditions clean,fact2fiction_p0.001,fact2fiction_p0.005,fact2fiction_p0.01,fact2fiction_p0.04,fact2fiction_p0.08 \
     --workers 6 --contract-retries 2

   PYTHONPATH=src:scripts .venv/bin/python scripts/check_evidence_signal.py \
     --config configs/stage1_environment_confirmation_train_v1.json \
     --protocol configs/environment_confirmation_protocol_v1.json \
     --run-root artifacts/runs/environment_confirmation_train_v1/evidence_signal/environment_confirmation_evidence_v1 \
     --conditions clean,fact2fiction_p0.001,fact2fiction_p0.005,fact2fiction_p0.01,fact2fiction_p0.04,fact2fiction_p0.08
   ```

5. Construct the leave-original-out view from the same clean-or-poisoned corpus, obtain mapped
   counter-view reports, audit exclusions, and only then run the frozen evaluation:

   ```bash
   PYTHONPATH=src:scripts .venv/bin/python scripts/run_counter_retrieval_signal.py \
     --config configs/stage1_environment_confirmation_train_v1.json \
     --source-run-root artifacts/runs/environment_confirmation_train_v1/evidence_signal/environment_confirmation_evidence_v1 \
     --experiment-id environment_confirmation_counter_v1 --phase all \
     --device cuda:0 --workers 6 --contract-retries 2

   PYTHONPATH=src:scripts .venv/bin/python scripts/check_counter_retrieval_signal.py \
     --config configs/stage1_environment_confirmation_train_v1.json \
     --source-run-root artifacts/runs/environment_confirmation_train_v1/evidence_signal/environment_confirmation_evidence_v1 \
     --run-root artifacts/runs/environment_confirmation_train_v1/counter_retrieval/environment_confirmation_counter_v1 \
     --require-maps

   PYTHONPATH=src:scripts .venv/bin/python scripts/evaluate_environment_confirmation.py \
     --protocol configs/environment_confirmation_protocol_v1.json \
     --endpoints artifacts/evaluation/environment_confirmation_train_v1/endpoint_summary.json \
     --counter-root artifacts/runs/environment_confirmation_train_v1/counter_retrieval/environment_confirmation_counter_v1
   ```

6. Interpret the frozen primary gate without retuning on these claims. After the complete
   same-model matrix is reported, implement and run the prespecified 1% GLM/Llama attacker-transfer
   secondary on the jointly clean-correct claims. That secondary runner is the only planned piece
   not yet implemented.

## 2026-08-12 — Resumed endpoint collection and evidence-map amendment

- Completed all 100 retrieval indexes, 300 clean RAG endpoints, 252 nested attack plans, and
  1,260 attacked RAG endpoints without unresolved failures.
- The per-victim clean-correct eligibility counts are GLM 89, Llama 86, and Qwen 77. The complete
  endpoint table contains 1,560 rows, including 787 RAG/internal-majority disagreements.
- Completed all 251 unique neutral claim plans and 786/787 original-view evidence reports.
- Seven initially failing reports exposed a generic prompt-rendering defect: literal braces in
  retrieved text were mistaken for template variables after insertion. The renderer now checks
  only variables present in the original template; regression tests cover both literal evidence
  braces and genuinely unresolved variables. No frozen prompt or model request changed.
- The remaining row contained one retrieved item made entirely of underscores. Eleven retained
  attempts consistently left that non-proposition's `key_assertion` empty, correctly failing the
  strict response contract. A gold-blind operational amendment was therefore frozen in
  `configs/environment_confirmation_protocol_v1_amendment_1.json`: remove only retrieved items
  that contain no alphanumeric character after prefix stripping. It does not change any endpoint,
  substantive evidence text, prompt, policy, threshold, or evaluation rule.

## 2026-08-12 — Counter-view resumability amendment

- Constructed all 787 leave-original-out retrieval records from the same clean-or-poisoned corpus.
  Each record excludes every originally retrieved document ID and exact passage-text hash.
- An operational restart exposed a quadratic remote-filesystem lookup in the mapping resume path:
  it scanned all packet directories for each row although the exact immutable paths were already
  in the retrieval manifest. The second gold-blind amendment now loads those recorded paths and
  falls back to deterministic reconstruction when absent.
- The change affects no packet byte, prompt, model request, response contract, policy input, or
  evaluation. The independent final audit still reconstructs all 787 packets and exclusions.

## 2026-08-12 — Non-content rule extended to the counter view

- The first complete counter-report pass accepted 783/787 rows. Three ordinary schema failures
  recovered with additional retained repair attempts.
- The sole persistent row was Llama claim 710 at four-percent poisoning. Its counter packet
  contained a four-line underscore separator; eleven attempts consistently produced an empty
  assertion for that item. This is the same mechanically detectable artifact covered by amendment
  1 in the original view.
- Amendment 3 extends the identical no-alphanumeric filter to counter packets. The affected packet
  retains all 23 substantive passages; no retrieval result, endpoint, label, policy, or threshold
  is changed.

## 2026-08-12 — Fresh same-model primary result

- The 787/787 counter-view reports pass reconstruction, exclusion, same-model, prompt-isolation,
  cache, and response-contract audits with zero unresolved failures.
- The frozen primary gate passes. Across 1,260 attacked rows, proposed accuracy is 80.48%, versus
  48.97% for RAG and 73.02% for three-call closed-book majority. On 300 clean rows, proposed is
  83.67% versus 84.00% for RAG.
- The proposed policy is strictly above both raw endpoints after pooling the five attacked rates
  separately for all three victims: GLM 81.12%, Llama 80.93%, and Qwen 79.22%.
- The prespecified attacker-transfer secondary is frozen separately in
  `configs/environment_attacker_transfer_v1.json`. Its scope is the 69 jointly clean-correct
  confirmation claims, two fixed 1% poison generators, and all three victims. No primary-policy
  component is changed.

## 2026-08-12 — Attacker-transfer secondary complete

- Completed all 414 endpoints: 69 jointly clean-correct claims in each of six GLM/Llama
  attacker-by-GLM/Llama/Qwen victim cells. The 138 diagonal endpoints were reused; 276
  off-diagonal endpoints used the unchanged victim workflow.
- One Qwen answer response required additional format-only repair attempts; the final endpoint
  matrix has zero unresolved failure.
- Found 188 RAG/internal disagreements over 128 unique victim/claim cases. Every neutral plan was
  reused from cache. Completed 188/188 same-corpus leave-original-out retrievals and same-victim
  counter reports with zero failure.
- The transfer audit passes all endpoint coverage, poison-source, same-victim call, prompt
  isolation, original-document/text exclusion, packet reconstruction, and output-contract checks.
- Frozen transfer performance is 83.09% proposed versus 58.94% RAG and 76.33% closed book pooled
  over 414 rows. Proposed beats both raw endpoints pooled separately for each victim. It does not
  dominate every cell: GLM-attacker/Qwen-victim is one case below closed book.
- Final paper-facing results, limitations, costs, and artifact pointers are in
  `docs/ENVIRONMENT_CONFIRMATION_RESULTS.md`.
