# run.py  —  entry point
#
# Usage:
#   python run.py --n 3           # smoke-test: run first 3 claims
#   python run.py                 # run all claims in dev.json
#   python run.py --start 10 --n 5   # run claims 10..14 (for resuming)
#
# WHY load_dotenv() at the very top (before any other import that uses env vars):
#   graph.py, llm_client.py, and result_store.py all read os.environ at
#   import time or at function call time. If dotenv isn't loaded first,
#   those reads get empty strings and fail silently or loudly.

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# ── Load .env BEFORE importing anything that reads os.environ ────────────────
load_dotenv(Path(__file__).parent / ".env")

# Now safe to import our modules
from graph import run_single_claim
from result_store import ensure_results_dir, write_eval_json, JSONL_PATH


def load_dev_data(path: str) -> list[dict]:
    """
    Read dev.json and return the list of claim records.
    Prints one sample to confirm the expected structure.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    print(f"[run] Loaded {len(data)} records from {path}")

    # Print the first record's key fields so you can sanity-check the data
    sample = data[0]
    print("[run] Sample record fields:")
    print(f"  claim_id : 0 (index)")
    print(f"  claim    : {sample['claim'][:80]!r}...")
    print(f"  label    : {sample['label']!r}")
    print(f"  (other fields like 'questions' are ignored in this experiment)")
    print()

    return data


def load_existing_ids() -> set[int]:
    """
    Read the JSONL file and collect claim_ids that were already processed.
    Lets you resume an interrupted run without re-processing finished claims.
    """
    if not JSONL_PATH.exists():
        return set()

    seen = set()
    with open(JSONL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                record = json.loads(line)
                seen.add(record["claim_id"])
    return seen


def main():
    parser = argparse.ArgumentParser(
        description="Baseline: LLM-only veracity prediction on AVeriTeC dev set."
    )
    parser.add_argument(
        "--n",
        type=int,
        default=None,
        help="Number of claims to process (default: all). Use --n 3 for a smoke test.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="Start from this claim index (0-based). Useful for resuming.",
    )
    parser.add_argument(
        "--data",
        type=str,
        default=os.environ.get("AVERITEC_DEV_PATH", "../DEFAME/data/AVeriTeC/dev.json"),
        help="Path to dev.json",
    )
    args = parser.parse_args()

    # ── Load data ─────────────────────────────────────────────────────────────
    data = load_dev_data(args.data)

    # Slice the range we want to process
    end_idx = args.start + args.n if args.n is not None else len(data)
    subset = data[args.start:end_idx]
    print(f"[run] Processing claims {args.start} to {args.start + len(subset) - 1} "
          f"({len(subset)} total)\n")

    # ── Skip already-processed claims (resume support) ────────────────────────
    already_done = load_existing_ids()
    if already_done:
        print(f"[run] Skipping {len(already_done)} already-processed claim_ids.\n")

    ensure_results_dir()

    # ── Main loop ─────────────────────────────────────────────────────────────
    all_records = []
    failed_parses = 0

    for offset, record in enumerate(subset):
        claim_id = args.start + offset   # absolute index in dev.json

        if claim_id in already_done:
            continue

        claim      = record["claim"]
        gold_label = record["label"]

        # run_single_claim invokes the LangGraph pipeline for this one claim
        final_state = run_single_claim(
            claim_id=claim_id,
            claim=claim,
            gold_label=gold_label,
        )

        if not final_state.get("parse_success"):
            failed_parses += 1

        all_records.append(final_state)

    # ── Write the evaluation-ready JSON at the end ────────────────────────────
    # Merge with any previously written records so the eval file is complete
    # WHY re-read JSONL: if this run was a partial (--n 3), we want eval.json
    # to contain ALL previously written records, not just today's batch.
    all_jsonl_records = []
    if JSONL_PATH.exists():
        with open(JSONL_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    all_jsonl_records.append(json.loads(line))

    write_eval_json(all_jsonl_records)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"Run complete.")
    print(f"  Processed this run : {len(all_records)}")
    print(f"  Parse failures     : {failed_parses}")
    print(f"  Results → {JSONL_PATH.parent}/")
    print("=" * 60)
    print("\nNext step — run evaluation:")
    print("  python evaluate_veracity_baseline.py "
          "--prediction_file results/predictions_for_eval.json "
          "--label_file ../averitec/data/dev.json")


if __name__ == "__main__":
    main()
