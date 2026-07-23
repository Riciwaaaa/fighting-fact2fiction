"""
Produce combined post-attack predictions CSVs matching DEFAME's predictions.csv format.
Runs for each MODEL entry in RUNS below.
"""
import json, re, csv
from pathlib import Path
from sklearn.metrics import f1_score, accuracy_score

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "experiments" / "runs" / "04_results_baseline_100claim"

# ── runs config ──────────────────────────────────────────────────────────────
RUNS = [
    {
        "model":       "deepseek_v4_flash",
        "docs_dir":    "DEFAME/out/averitec/infact/deepseek_v4_flash/2026-07-05_20-20/docs",
        "attack_jsonl":"Fact2Fiction/src/attack/attack_results/dev_fact2fiction_infact_0.08/results/attack_results_deepseek_v4_flash_att_deepseek_v4_flash.jsonl",
        "out_csv":     "combined_results_deepseek_v4_flash_100.csv",
    },
    {
        "model":       "mimo_v25_pro",
        "docs_dir":    "DEFAME/out/averitec/infact/mimo_v25_pro/2026-07-05_03-00/docs",
        "attack_jsonl":"Fact2Fiction/src/attack/attack_results/dev_fact2fiction_infact_0.08/results/attack_results_mimo_v25_pro_att_deepseek_v4_flash.jsonl",
        "out_csv":     "combined_results_mimo_v25_pro_100.csv",
    },
    {
        "model":       "minimax_m3",
        "docs_dir":    "DEFAME/out/averitec/infact/minimax_m3/2026-07-04_20-54/docs",
        "attack_jsonl":"Fact2Fiction/src/attack/attack_results/dev_fact2fiction_infact_0.08/results/attack_results_minimax_m3_att_deepseek_v4_flash.jsonl",
        "out_csv":     "combined_results_minimax_m3_100.csv",
    },
]

DEV_JSON = REPO_ROOT / "DEFAME" / "data" / "AVeriTeC" / "dev.json"
# ─────────────────────────────────────────────────────────────────────────────

GT_LABEL_MAP = {
    "Refuted": "REFUTED",
    "Supported": "SUPPORTED",
    "Not Enough Evidence": "NEI",
    "Conflicting Evidence/Cherrypicking": "CONFLICTING",
}

DEFAME_VERDICT_MAP = {
    "SUPPORTED": "SUPPORTED",
    "REFUTED": "REFUTED",
    "NEI": "NEI",
    "CONFLICTING": "CONFLICTING",
    "CHERRY_PICKING": "CONFLICTING",
}

ATTACK_PRED_MAP = {
    "supported": "SUPPORTED",
    "refuted": "REFUTED",
    "not enough information": "NEI",
    "not enough evidence": "NEI",
    "nei": "NEI",
    "conflicting evidence/cherrypicking": "CONFLICTING",
    "conflicting": "CONFLICTING",
}

LABEL_ORDER = ["SUPPORTED", "REFUTED", "NEI", "CONFLICTING"]

def parse_verdict(doc_path):
    text = doc_path.read_text()
    m = re.search(r"### Verdict:\s*(\S+)", text)
    if not m:
        return None
    return DEFAME_VERDICT_MAP.get(m.group(1).strip().upper())

def parse_justification(doc_path):
    text = doc_path.read_text()
    m = re.search(r"### Justification\n(.*?)(?=\n##|\Z)", text, re.DOTALL)
    if not m:
        return ""
    return m.group(1).strip()

# ── load ground truth once ───────────────────────────────────────────────────
OUT_DIR.mkdir(parents=True, exist_ok=True)

with open(DEV_JSON) as f:
    dev = json.load(f)

gt_labels         = {i: GT_LABEL_MAP[dev[i]["label"]] for i in range(100)}
gt_justifications = {i: dev[i].get("justification", "") for i in range(100)}
claim_texts       = {i: dev[i]["claim"] for i in range(100)}

# ── process each run ─────────────────────────────────────────────────────────
for run in RUNS:
    model        = run["model"]
    docs_dir     = REPO_ROOT / run["docs_dir"]
    attack_jsonl = REPO_ROOT / run["attack_jsonl"]
    out_csv      = OUT_DIR / run["out_csv"]

    # original InFact predictions from DEFAME docs
    original_verdicts       = {}
    original_justifications = {}
    for i in range(100):
        doc = docs_dir / f"{i}.md"
        original_verdicts[i]       = parse_verdict(doc)
        original_justifications[i] = parse_justification(doc)

    # attack results
    attacked = {}
    with open(attack_jsonl) as f:
        for line in f:
            r   = json.loads(line)
            cid = int(r["claim_id"])
            attacked[cid] = {
                "pred_label":    ATTACK_PRED_MAP.get(r["pred_label"].lower(), r["pred_label"].upper()),
                "justification": r.get("after_justification", ""),
            }

    # build rows
    rows = []
    for i in range(100):
        if i in attacked:
            predicted     = attacked[i]["pred_label"]
            justification = attacked[i]["justification"]
        else:
            predicted     = original_verdicts[i]
            justification = original_justifications[i]

        rows.append({
            "sample_index":    i,
            "claim":           claim_texts[i],
            "target":          gt_labels[i],
            "predicted":       predicted,
            "justification":   justification,
            "correct":         (gt_labels[i] == predicted),
            "gt_justification": gt_justifications[i],
        })

    # write CSV
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "sample_index", "claim", "target", "predicted",
            "justification", "correct", "gt_justification"
        ])
        writer.writeheader()
        writer.writerows(rows)

    # metrics
    y_true   = [r["target"]    for r in rows]
    y_pred   = [r["predicted"] for r in rows]
    acc      = accuracy_score(y_true, y_pred)
    f1_per   = f1_score(y_true, y_pred, labels=LABEL_ORDER, average=None, zero_division=0)
    macro_f1 = f1_score(y_true, y_pred, labels=LABEL_ORDER, average="macro", zero_division=0)
    n_correct = sum(1 for r in rows if r["correct"])

    print(f"\n{'='*55}")
    print(f"Model : {model}")
    print(f"CSV   : {out_csv}")
    print(f"Attacked : {len(attacked)} / Original : {100 - len(attacked)}")
    print(f"Accuracy : {acc:.4f}  ({n_correct}/100)")
    print(f"Per-class F1:")
    for lbl, score in zip(LABEL_ORDER, f1_per):
        print(f"  {lbl:<12}: {score:.4f}")
    print(f"Macro-F1 : {macro_f1:.4f}")
