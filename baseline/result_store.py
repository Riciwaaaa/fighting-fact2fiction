# result_store.py

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).parent / "results"
JSONL_PATH  = RESULTS_DIR / "predictions.jsonl"
CSV_PATH    = RESULTS_DIR / "predictions.csv"
EVAL_PATH   = RESULTS_DIR / "predictions_for_eval.json"

CSV_FIELDNAMES = [
    "claim_id",
    "claim",
    "gold_label",
    "predicted_label",
    "raw_model_output",
    "thinking_trace",
    "parse_success",
    "latency_ms",
    "timestamp",
    "model_name",
]


def ensure_results_dir() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _open_csv_writer():
    file_exists = CSV_PATH.exists()
    f = open(CSV_PATH, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
    if not file_exists:
        writer.writeheader()
    return f, writer


def append_result(record: dict[str, Any]) -> None:
    """Write one record to JSONL and CSV immediately (no buffering)."""
    ensure_results_dir()

    with open(JSONL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    f, writer = _open_csv_writer()
    csv_row = {k: record.get(k, "") for k in CSV_FIELDNAMES}
    writer.writerow(csv_row)
    f.close()


def write_eval_json(records: list[dict[str, Any]]) -> None:
    """
    Write predictions_for_eval.json for evaluate_veracity_baseline.py.
    Format: [{"pred_label": "Supported"}, ...]
    evaluate_veracity() only reads pred_label, so no evidence field needed.
    """
    ensure_results_dir()
    eval_records = [
        {"pred_label": r.get("predicted_label", "Not Enough Evidence")}
        for r in records
    ]
    with open(EVAL_PATH, "w", encoding="utf-8") as f:
        json.dump(eval_records, f, ensure_ascii=False, indent=2)
    print(f"[result_store] Wrote {len(eval_records)} predictions → {EVAL_PATH}")


def make_record(
    *,
    claim_id: int,
    claim: str,
    gold_label: str,
    predicted_label: str | None,
    raw_model_output: str,
    thinking_trace: str,
    parse_success: bool,
    latency_ms: float,
    model_name: str,
) -> dict[str, Any]:
    return {
        "claim_id":         claim_id,
        "claim":            claim,
        "gold_label":       gold_label,
        "predicted_label":  predicted_label or "Not Enough Evidence",
        "raw_model_output": raw_model_output,
        "thinking_trace":   thinking_trace,
        "parse_success":    parse_success,
        "latency_ms":       round(latency_ms, 1),
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "model_name":       model_name,
    }
