# Fighting Fact2Fiction — Project Overview

Defending the **InFact** fact-checker against the **Fact2Fiction** knowledge-base
poisoning attack, using the fact-checker model's own internal knowledge plus a
**sub-claim-level evidence-verification** defense.

- **Attack (Fact2Fiction):** injects fabricated "evidence" documents (URLs ending in
  `/created`) into a claim's local knowledge base, so a retrieval-based fact-checker
  adopts the fakes and flips its verdict.
- **Victim (InFact):** a QA-based fact-checker — decompose a claim into sub-questions,
  retrieve evidence per question, answer each, then judge the whole document.
- **Our defense:** localize where the poisoned fact-check disagrees with a
  retrieval-free "model-only" reasoner, probe the suspect evidence for the
  *corroborating context* a real event would leave behind (fabrications have none),
  discredit what fails verification, and let InFact's own judge re-verdict.

Task is restricted to a **binary** (Supported / Refuted) subset of AVeriTeC.

---

## 1. Repository layout

```
fighting-fact2fiction/
├── DEFAME/                     # InFact impl. #1 — used for CLEAN-KB work & the benchmark
│   ├── infact/                 #   the fact-checking library (eval, tools, modules, prompts)
│   ├── data/AVeriTeC/          #   dataset: dev.json, dev_binary.json, test/train.json
│   │   └── knowledge_base/     #   ~48 GB downloaded KB  (NOT in git — see §6)
│   ├── config/                 #   globals, model registry, API keys (keys gitignored)
│   └── scripts/                #   DEFAME entry points (averitec/evaluate.py, run.py)
│
├── Fact2Fiction/               # InFact impl. #2 (a separate copy) + the ATTACK
│   └── src/
│       ├── infact/             #   second copy of the fact-checking library
│       ├── attack/             #   the Fact2Fiction poisoning attack (main.py, attack_utils.py)
│       │   ├── attack_results/ #     cached poison artifacts (pkls)  (NOT in git — regenerable)
│       │   └── attack_cache/   #     cached embeddings              (NOT in git — regenerable)
│       ├── fc_results/         #   pristine pre-attack InFact reports per model
│       └── config/
│
├── baseline/                   # model-only fact-checking primitives
│   ├── llm_client.py           #   OpenRouter call wrapper (call_glm)
│   ├── label_parser.py         #   verdict-string -> canonical label (binary-aware)
│   └── .env                    #   OPENROUTER_API_KEY (gitignored)
│
├── experiments/                # THE PIPELINE (all our work) — see §3, §4
│   ├── *.py                    #   pipeline + analysis scripts
│   └── runs/                   #   per-run outputs (results kept in git; see §6)
│
└── PROJECT_OVERVIEW.md         # this file
```

### Why two copies of `infact`?
`DEFAME/infact` and `Fact2Fiction/src/infact` are **near-identical but separate** Python
packages that both import as `infact` / `config`. They **cannot coexist in one
interpreter** (name collision). So the pipeline enforces strict process separation:

- **Clean-KB / benchmark side** → runs under `DEFAME/` (cwd + sys.path).
- **Attack / poisoned-KB / re-judge side** → runs under `Fact2Fiction/src/`.
- The two sides communicate **only via JSON files on disk**, never in-process.

Any edit to the shared benchmark/label space (e.g. `AVeriTeCBinary`) must be applied to
**both** copies or one goes stale.

---

## 2. Data

- **AVeriTeC dev** = 500 claims, 4 gold labels (Supported / Refuted / Not Enough
  Evidence / Conflicting Evidence-Cherrypicking).
- **`dev_binary.json`** (`experiments/make_binary_averitec.py`) = the 427 Supported/Refuted
  claims only, each carrying an `orig_id` so its claim id still equals its original
  `dev.json` array position (this keeps every cached poison artifact valid).
- **`AVeriTeCBinary`** benchmark class (in both `infact/eval/benchmark.py` copies) loads
  `dev_binary.json` and offers the judge only Supported/Refuted.
- **Attack-eligible pool = 53 claims**: the binary claims that InFact answered
  *correctly before* the attack (`get_all_valid_claim_ids`). All experiments run on
  subsets of these 53.

---

## 3. The pipeline (4 stages)

Each stage is a script under `experiments/`; each reads the previous stage's JSON and
writes into a run directory (`experiments/runs/<run>/`). Default `--results-dir` points
at `runs/03_mimo_27claim_binary` (the current run).

```
                 make_binary_averitec.py ──► DEFAME/data/AVeriTeC/dev_binary.json
                                                     │
  ┌──────────────────────────────────────────────────┼───────────────────────────────┐
  │ Stage 1  run_attacked_infact.py   (Fact2Fiction env)                               │
  │   poison the KB (cached) → run InFact → dump attacked verdict + adopted evidence    │
  │   out: runs/<run>/attacked_infact_dumps/{cid}.json                                 │
  └──────────────────────────────────────────────────┬───────────────────────────────┘
                                                     │
  ┌──────────────────────────────────────────────────┼───────────────────────────────┐
  │ Stage 2  infact_supplement.py     (DEFAME env)                                     │
  │   model-only fact-check (evidence_rag_probe.factcheck_*) → verdict + reasoning      │
  │   bullets;  AGREEMENT SKIP-GATE: if model-only == poisoned verdict, stop here       │
  │   else gap-detect what InFact missed                                               │
  │   out: runs/<run>/infact_supplement.jsonl                                           │
  └──────────────────────────────────────────────────┬───────────────────────────────┘
                                                     │
  ┌──────────────────────────────────────────────────┼───────────────────────────────┐
  │ Stage 3  subclaim_defense.py      (Fact2Fiction env)   ← THE DEFENSE                │
  │   A Bulletize  InFact sub-claims + adopted evidence  vs  model-only points          │
  │   B Align      per sub-claim: agrees / mismatch / unconsidered                      │
  │   C Materiality gate: drop anything that can't change the verdict                   │
  │   D Angles     model-only proposes corroboration-probing verification queries       │
  │   E Verify     retrieve vs POISONED KB → trust: fabricated/doubtful/trustworthy     │
  │                → re-answer from trustworthy evidence, else mark UNRESOLVED           │
  │   F Supplement add material missing points                                         │
  │   G Re-judge   InFact's own Judge over the cleaned Q&A                              │
  │   out: runs/<run>/subclaim_defense/{cid}.json  (full per-stage trace + verdict)     │
  └──────────────────────────────────────────────────┬───────────────────────────────┘
                                                     │
  ┌──────────────────────────────────────────────────┼───────────────────────────────┐
  │ Stage 4  eval_table.py  +  analyze_defense.py                                      │
  │   eval_table.py     → 4-system comparison (Acc / F1 / Macro-F1)                     │
  │   analyze_defense.py → T1..T6 analysis (oracle ceiling, defense success rate,       │
  │                        fabrication-detection matrix, complementarity, skip-gate)    │
  │   out: runs/<run>/eval_table.{md,csv}, eval_predictions.csv, analysis.md, analysis_*.csv │
  └────────────────────────────────────────────────────────────────────────────────────┘
```

**Four systems compared** (per claim, canonical labels):
`model_only`  ·  `infact` (clean, == gold by construction on this set)  ·
`f2f_poisoned_infact`  ·  `subclaim_verified_poisoned_infact` (the defense).

---

## 4. Scripts reference (`experiments/`)

| Script | Stage | Env | Role |
|---|---|---|---|
| `make_binary_averitec.py` | data | any | build `dev_binary.json` |
| `run_attacked_infact.py` | 1 | Fact2Fiction | run poisoned InFact, dump attacked verdict + evidence |
| `evidence_rag_probe.py` | 2 (lib) | DEFAME | model-only fact-check: 2 calls (plain reasoning bullets → verdict, then query generation) |
| `infact_supplement.py` | 2 | DEFAME | model-only verdict + gap detection + agreement skip-gate |
| `poisoned_kb.py` | 3 (lib) | Fact2Fiction | reconstruct poisoned per-claim KB (fresh KNN refit + disk cache) |
| `subclaim_defense.py` | 3 | Fact2Fiction | the sub-claim verification defense (stages A–G) |
| `rejudge_assisted.py` | (old) | Fact2Fiction | superseded document-level additive-merge defense |
| `eval_table.py` | 4 | any (sklearn) | 4-system metrics table |
| `analyze_defense.py` | 4 | any | T1–T6 analysis tables + CSVs |
| `combine_results.py` | side | any (sklearn) | baseline 100-claim combined CSVs (separate track) |
| `combine_all_runs.py` | side | any | long-format CSV across all 4 runs |
| `combine_run03_wide.py` | side | any | wide-format per-claim CSV for run 03 |

**Interpreter:** everything that touches the KB/embeddings/sklearn must run under
`/home/ubuntu/.venv312/bin/python3.12` (CPU-only). Pure-JSON scripts (`analyze_defense`,
`combine_*`) run under plain `python3`.

### Key mechanisms
- **Two-call model-only** (`evidence_rag_probe.py`): call 1 emits plain atomic reasoning
  bullets + a verdict (no prose justification); call 2 generates a web-search query per
  bullet. Keeps reasoning undistorted by query-writing.
- **Agreement skip-gate** (`canon()` in `infact_supplement.py` / `subclaim_defense.py`):
  if the model-only verdict already equals the poisoned verdict, there is nothing to
  correct → skip the whole defense, carry the original verdict.
- **Materiality gate** (Stage C): only verify a discrepancy if resolving it could
  plausibly change the verdict; everything else is dropped before any expensive call.
- **Corroboration probing** (Stages D–E): verification queries probe *around* the
  assertion (independent coverage, the actor's later reaction, criticism it would have
  provoked, fact-check coverage) — a real event leaves that trace, a fabrication does
  not. Absence of corroboration ⇒ `fabricated`. Retrieval runs against the **poisoned**
  KB (realistic: a deployed system can't reach a clean corpus).
- **All prompts** are written in InFact's house style (see
  `Fact2Fiction/src/infact/prompts/{judge,propose_queries,pose_questions_json}.md`).

---

## 5. Experiment runs (`experiments/runs/`)

See `experiments/runs/README.md` for details. Summary:

| Run | Claims | Model | Notes |
|---|---|---|---|
| `01_deepseek_10claim` | 10 | deepseek-v4 | earliest, single-call model-only, superseded |
| `02_mimo_27claim_4class` | 27 | mimo-v2.5-pro | pre-binary; document-level additive-merge defense (didn't work) |
| `03_mimo_27claim_binary` | 53 | mimo-v2.5-pro | **current/final** — binary, sub-claim defense |
| `04_results_baseline_100claim` | 100 | 4 models | pre-attack vs post-attack baseline (separate track) |

**Current headline result (`03`, N=53):** the sub-claim defense lifts poisoned InFact
accuracy **0.642 → 0.868** (matching the model-only reasoner) with **zero regressions**;
the fabrication detector is **100% recall / 0% false-positive** over 78 verified
sub-claims. Full numbers in `runs/03_mimo_27claim_binary/analysis.md`.

---

## 6. What is and isn't version-controlled

**Committed** (small, and the actual research record):
- all code (`experiments/*.py`, `baseline/`, both `infact` libraries, attack code)
- small dataset JSONs (`dev.json`, `dev_binary.json`, `test.json`, `train.json`)
- small pre-attack reports (`Fact2Fiction/src/fc_results/`)
- **all run outputs** under `experiments/runs/` (verdicts, traces, tables — ~13 MB total)

**Gitignored** (large, regenerable, or downloaded — never commit):
- `DEFAME/data/AVeriTeC/knowledge_base/` — the ~48 GB downloaded KB (files up to 11 GB;
  far over GitHub's 100 MB/file limit)
- `Fact2Fiction/src/attack/attack_results/` + `attack_cache/` — ~1.1 GB poison/embedding caches
- `DEFAME/out/`, `Fact2Fiction/src/out/`, `baseline/results/` — regenerable outputs
- secrets (`baseline/.env`, `DEFAME/config/api_keys.yaml`), `__pycache__/`, venvs

Rule of thumb: **commit code + the small result files** (they're the record of what we
found); **never commit the multi-GB knowledge base or the poison caches** — they are
downloaded/regenerable and would blow past GitHub's limits.
