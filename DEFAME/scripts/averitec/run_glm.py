"""Sequential InFact run for AVeriTeC dev claims using GLM-5.2 via OpenRouter.

Why sequential (not the built-in evaluate())?
evaluate() uses a multiprocessing Pool designed for local GPU models.
For API-based models we need zero GPUs; the d % n_devices expression crashes
when n_devices=0. A simple loop is cleaner and equally fast for rate-limited APIs.

Usage (run from DEFAME/ directory):
    python scripts/averitec/run_glm.py              # 100 claims
    python scripts/averitec/run_glm.py --n 10       # quick smoke test
    python scripts/averitec/run_glm.py --n 100 --data ../averitec/data/dev.json
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure DEFAME root is importable when called from any working directory
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infact.common.content import Content
from infact.common.label import Label
from infact.fact_checker import FactChecker

# --- AVeriTeC label configuration --------------------------------------------

# Mirrors AVeriTeC.class_definitions in infact/eval/benchmark.py.
# These descriptions guide the LLM judge to use AVeriTeC's exact taxonomy.
AVERITEC_CLASS_DEFS = {
    Label.SUPPORTED: (
        "The knowledge from the fact-check supports or at least strongly implies the Claim. "
        "Mere plausibility is not enough for this decision."
    ),
    Label.NEI: (
        "The fact-check does not contain sufficient information to come to a conclusion. "
        "In particular, there is substantial lack of both supporting and refuting evidence."
    ),
    Label.REFUTED: (
        "The knowledge from the fact-check explicitly and clearly refutes at least substantial "
        "parts if not even the whole Claim."
    ),
    Label.CONFLICTING: (
        "The Claim has both supporting and refuting evidence from multiple sources."
    ),
    Label.CHERRY_PICKING: (
        "The Claim is technically true but misleads by excluding important context. "
        "Including that context would create a significantly different impression. "
        "Pick this decision also if the Claim is not universally true but true under certain conditions."
    ),
}

# Per DEFAME paper: cherry-picking is merged into conflicting for final scoring
# (AVeriTeC only has 4 official classes, not 5)
LABEL_TO_AVERITEC_STR = {
    Label.SUPPORTED:      "Supported",
    Label.REFUTED:        "Refuted",
    Label.NEI:            "Not Enough Evidence",
    Label.CONFLICTING:    "Conflicting Evidence/Cherrypicking",
    Label.CHERRY_PICKING: "Conflicting Evidence/Cherrypicking",  # merged
}

# Extra rule to avoid the argument-from-ignorance fallacy (from benchmark.py)
EXTRA_JUDGE_RULES = (
    '* **Do not commit the "argument from ignorance" fallacy**: The absence of evidence '
    "for the Claim does NOT prove that the Claim is refuted. Instead, the Claim is simply "
    "unsupported — which is a case of 'not enough information'."
)

# Gold label string from dev.json → Label enum (for computing accuracy locally)
STR_TO_LABEL = {v: k for k, v in LABEL_TO_AVERITEC_STR.items() if k != Label.CHERRY_PICKING}
STR_TO_LABEL["Cherry-picking"] = Label.CHERRY_PICKING  # dev.json uses hyphen


# --- Main --------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--n",     type=int, default=100,
                   help="Number of claims to evaluate (default: 100)")
    p.add_argument("--start", type=int, default=0,
                   help="Index of first claim (for resuming or batching)")
    p.add_argument("--data",  type=str, default="../averitec/data/dev.json",
                   help="Path to AVeriTeC dev.json (relative to DEFAME/ dir)")
    return p.parse_args()


def main():
    args = parse_args()

    # --- Load data ---
    data_path = Path(args.data)
    if not data_path.exists():
        print(f"ERROR: data file not found: {data_path.resolve()}")
        print("Tip: run from DEFAME/ dir, or set --data to the correct path.")
        sys.exit(1)

    with open(data_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    samples = raw_data[args.start: args.start + args.n]
    print(f"Loaded {len(samples)} claims (indices {args.start}–{args.start + len(samples) - 1})")

    # --- Output directory ---
    out_dir = Path("out/averitec/infact/gemini_35_flash")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path  = out_dir / "predictions.csv"
    json_path = out_dir / "averitec_out.json"

    # Resume: skip claims already processed in a previous partial run
    done_ids: set[int] = set()
    existing_preds: list[dict] = []
    existing_rows:  list[dict] = []

    if json_path.exists():
        with open(json_path, "r") as f:
            existing_preds = json.load(f)
        done_ids = {r["claim_id"] for r in existing_preds}
        print(f"Resuming: {len(done_ids)} claims already done, skipping them.")

    if csv_path.exists():
        with open(csv_path, "r", newline="", encoding="utf-8") as f:
            existing_rows = list(csv.DictReader(f))

    # --- Build model explicitly to pass reasoning_effort ---
    # We instantiate the model here (not inside FactChecker) so we can control reasoning_effort.
    # "high" = extended thinking but not maximum; faster than "xhigh" while still reasoning.
    # The baseline uses xhigh because it has no evidence and must rely purely on internal knowledge.
    # Here, InFact retrieves evidence externally, so "high" is sufficient.
    from infact.common.modeling import make_model
    llm = make_model("gemini_35_flash", reasoning_effort="high")

    # --- Build FactChecker ---
    # search_engines={"duckduckgo": {}} — no local KB needed, free, no API key required.
    # Switch to {"google": {}} + serper_api_key in api_keys.yaml for higher quality / quota.
    fc = FactChecker(
        llm=llm,                               # pass model object directly (already instantiated)
        search_engines={"duckduckgo": {}},
        procedure_variant="infact",
        max_iterations=3,
        max_result_len=64_000,                 # chars per search result (same as original paper)
        class_definitions=AVERITEC_CLASS_DEFS,
        extra_judge_rules=EXTRA_JUDGE_RULES,
        print_log_level="info",
    )

    # --- Run ---
    predictions = list(existing_preds)
    csv_rows    = list(existing_rows)

    CSV_FIELDS = ["claim_id", "claim", "gold_label", "pred_label",
                  "justification", "parse_success", "latency_ms", "timestamp"]

    for i, raw in enumerate(samples):
        claim_id = raw.get("claim_id", args.start + i)

        if claim_id in done_ids:
            continue  # already processed in a previous run

        claim_text = raw["claim"]
        gold_str   = raw.get("label", "")
        print(f"\n[{i + 1}/{len(samples)}] claim_id={claim_id}: {claim_text[:90]}...")

        # Build Content with id_number so internal logs reference the correct claim
        content = Content(
            text=claim_text,
            author=raw.get("speaker", ""),
            origin=raw.get("original_claim_url", ""),
            id_number=claim_id,
        )

        start = time.time()
        parse_success = True
        justification = ""
        q_and_a = []

        try:
            pred_enum, docs, metas = fc.check_content(content)
            latency_ms = int((time.time() - start) * 1000)

            # Merge cherry-picking → conflicting (AVeriTeC has no separate 5th class)
            if pred_enum == Label.CHERRY_PICKING:
                pred_enum = Label.CONFLICTING

            pred_label = LABEL_TO_AVERITEC_STR.get(pred_enum, "Not Enough Evidence")
            justification = docs[0].justification if docs else ""
            q_and_a = metas[0].get("q_and_a", []) if metas else []

        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            pred_label = "Not Enough Evidence"
            justification = f"ERROR: {e}"
            parse_success = False
            print(f"  ERROR: {e}")

        # AVeriTeC evaluator format (evaluate_veracity.py reads this)
        out_instance = {
            "claim_id": claim_id,
            "claim":    claim_text,
            "pred_label": pred_label,
        }
        if q_and_a:
            out_instance["evidence"] = q_and_a  # enables Q&A scoring in original evaluator
        predictions.append(out_instance)

        csv_rows.append({
            "claim_id":     claim_id,
            "claim":        claim_text,
            "gold_label":   gold_str,
            "pred_label":   pred_label,
            "justification": justification,
            "parse_success": parse_success,
            "latency_ms":   latency_ms,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        })

        # Flush after every claim — crash-safe
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(predictions, f, indent=2, ensure_ascii=False)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(csv_rows)

        print(f"  Pred: {pred_label} | Gold: {gold_str} | {latency_ms} ms")

        # Brief pause to respect DuckDuckGo rate limits
        time.sleep(1)

    # --- Summary ---
    correct = sum(
        1 for r in csv_rows
        if r["pred_label"] == r["gold_label"]
        or (r["pred_label"] == "Conflicting Evidence/Cherrypicking"
            and r["gold_label"] == "Cherry-picking")
    )
    print(f"\nDone! {len(csv_rows)} claims processed.")
    print(f"Quick accuracy (local): {correct}/{len(csv_rows)} = {correct/len(csv_rows):.3f}")
    print(f"\nResults saved to {out_dir}/")
    print(f"\nTo run official evaluation (from project root):")
    print(f"  cd averitec")
    print(f"  python prediction/evaluate_veracity.py \\")
    print(f"    --predictions ../DEFAME/{json_path} \\")
    print(f"    --data_path data/dev.json")


if __name__ == "__main__":
    main()
