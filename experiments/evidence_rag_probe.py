"""
Evidence-RAG grounding probe.

For each claim: ask the model-only baseline to fact-check the claim AND bulletize
every piece of evidence it relied on, with one search query per evidence bullet.
Then retrieve each query against the claim's local AVeriTeC knowledge base and
record the top-k documents with their kNN distance scores, so we can inspect
whether model-generated evidence is actually groundable in the retrievable corpus.

Must run under /home/ubuntu/.venv312/bin/python3.12 (the only interpreter with
torch/sentence-transformers/sklearn installed).
"""

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

try:
    import torch  # noqa: F401
except ImportError:
    sys.exit(
        "This script requires torch. Run it with:\n"
        "  /home/ubuntu/.venv312/bin/python3.12 experiments/evidence_rag_probe.py ..."
    )

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = REPO_ROOT / "baseline"
DEFAME_DIR = REPO_ROOT / "DEFAME"

sys.path.insert(0, str(BASELINE_DIR))
from label_parser import parse_label, OFFICIAL_LABELS, BINARY_LABELS  # noqa: E402


def load_env_file(path: Path) -> None:
    """Minimal .env loader (python-dotenv is not installed in this venv)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(BASELINE_DIR / ".env")

from llm_client import call_glm  # noqa: E402

# KB import must happen with DEFAME on sys.path and as cwd (its config module
# uses relative paths, e.g. config/globals.py reads "config/api_keys.yaml" and
# KnowledgeBase resolves data_base_dir="data/" against cwd on EVERY file
# access, not just at import time). Do this AFTER the baseline imports above
# so the `config`/`infact` package names resolve to the DEFAME copies only.
#
# IMPORTANT: cwd must stay DEFAME_DIR for the lifetime of the process — both
# KnowledgeBase(...) construction and every later kb._get_resources()/retrieve()
# call resolve those relative paths against whatever cwd is *at call time*.
# Restoring the original cwd here (as an earlier version of this script did)
# makes KnowledgeBase think the KB isn't built and re-download the full
# multi-GB AVeriTeC knowledge store into the wrong directory.
_original_cwd = os.getcwd()
sys.path.insert(0, str(DEFAME_DIR))
os.chdir(DEFAME_DIR)
from infact.tools.search.knowledge_base import KnowledgeBase  # noqa: E402


# Decision-option blocks and verdict enums, swapped for binary vs full-class mode.
# Wording follows InFact's own class_definitions (see infact/eval/benchmark.py).
DECISION_OPTIONS_FULL = """\
* `Supported`: The claim is accurate and well-supported by your established knowledge.
* `Refuted`: The claim contradicts your established knowledge or is demonstrably false.
* `Not Enough Evidence`: You lack sufficient reliable knowledge to confirm or deny the claim, \
or the claim is too obscure or specific to assess confidently.
* `Conflicting Evidence/Cherrypicking`: You know of credible information both supporting and \
contradicting the claim, or the claim is technically true but misleads by omitting important context."""

DECISION_OPTIONS_BINARY = """\
* `Supported`: The claim is accurate and well-supported by your established knowledge.
* `Refuted`: The claim contradicts your established knowledge or is demonstrably false.

You must decide between exactly these two options. Even if your confidence is low, commit to your \
best judgement rather than hedging."""

VERDICT_ENUM_FULL = "Supported, Refuted, Not Enough Evidence, Conflicting Evidence/Cherrypicking"
VERDICT_ENUM_BINARY = "Supported, Refuted"

# Call 1 — fact-check. The model reasons as plain atomic bullet points (its thinking IS the list of
# points, no separate justification paragraph) and commits to a verdict. Style mirrors InFact's
# judge.md / pose_questions_json.md (# Instructions, numbered steps, `* ` rules, JSON list output).
FACTCHECK_PROMPT_TEMPLATE = """\
# Instructions
You are a fact-checker with broad world knowledge. Your task is to assess the veracity of a Claim \
**using only your own internal knowledge and reasoning** -- no external sources, no retrieved \
documents, no web search. Do this by following these steps:
1. Think through the Claim as a sequence of atomic reasoning points. Each point states exactly ONE \
discrete fact or inference you know that bears on the Claim's veracity.
2. From those points, decide which of the Decision Options best describes the Claim. You must choose \
your final decision from the Decision Options.

Always adhere to the following rules:
* **Reason in plain atomic points**: Each point must be a single, self-contained factual statement. \
Do not bundle multiple facts into one point, and do not write a separate summary or justification \
paragraph -- your list of points is your reasoning.
* **Use only your internal knowledge**: Do not assume access to any retrieved evidence.
* Be explicit and avoid pronouns or generic terms in place of names or objects, so each point can \
be understood on its own.
* Output in JSON format exactly as shown under "Output format".

## Decision Options
[DECISION_OPTIONS]

## Claim
[CLAIM]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, in exactly this shape:

```json
{
  "reasoning_steps": [
    "<atomic factual point>",
    "<atomic factual point>"
  ],
  "verdict": "<one of: [VERDICT_ENUM]>"
}
```
"""

# Call 2 — query generation. Separated from the fact-check so the reasoning above is not distorted by
# having to co-emit queries. Style mirrors InFact's propose_queries.md.
QUERY_PROMPT_TEMPLATE = """\
# Instructions
You are a fact-checker verifying a Claim. A knowledge-only reasoner has already broken the Claim \
down into a numbered list of atomic Reasoning Points. **Your task right now is to propose one \
web-search query per point** that aims to retrieve a real source confirming or refuting that \
specific point. Additionally, follow these rules:
* Propose exactly one query for each numbered point, in the same order.
* Be explicit and self-contained: do not use pronouns or generic terms in place of names or objects.
* Be brief; do not justify your queries.
* Output in JSON format exactly as shown under "Output format".

## Claim
[CLAIM]

## Reasoning Points
[POINTS]

## Output format
Respond with ONLY a single fenced JSON code block, no other prose, in exactly this shape (one query \
string per point, in order):

```json
{
  "queries": [
    "<search query for point 1>",
    "<search query for point 2>"
  ]
}
```
"""

REPAIR_SUFFIX = "\n\nYour previous response could not be parsed as valid JSON. " \
    "Return ONLY the JSON object in a fenced ```json code block. No other text."


def build_factcheck_prompt(claim: str, binary: bool = False) -> str:
    options = DECISION_OPTIONS_BINARY if binary else DECISION_OPTIONS_FULL
    verdict_enum = VERDICT_ENUM_BINARY if binary else VERDICT_ENUM_FULL
    return (FACTCHECK_PROMPT_TEMPLATE
            .replace("[DECISION_OPTIONS]", options)
            .replace("[VERDICT_ENUM]", verdict_enum)
            .replace("[CLAIM]", claim))


def build_query_prompt(claim: str, steps: list[str]) -> str:
    points = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
    return (QUERY_PROMPT_TEMPLATE
            .replace("[CLAIM]", claim)
            .replace("[POINTS]", points))


def _extract_json_block(text: str) -> dict | None:
    """Best-effort extraction of the first JSON object from model output."""
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = match.group(1) if match else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]
    if candidate is None:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def parse_factcheck_json(text: str) -> dict | None:
    """Extract {"reasoning_steps": [str, ...], "verdict": str} from the fact-check call."""
    data = _extract_json_block(text)
    if data is None:
        return None
    steps = data.get("reasoning_steps")
    if not isinstance(steps, list) or not steps:
        return None
    steps = [str(s).strip() for s in steps if str(s).strip()]
    if not steps:
        return None
    return {"reasoning_steps": steps, "verdict": data.get("verdict", "")}


def parse_query_json(text: str, n_steps: int) -> list[str] | None:
    """Extract {"queries": [str, ...]} aligned to n_steps. Pads/truncates to length."""
    data = _extract_json_block(text)
    if data is None:
        return None
    queries = data.get("queries")
    if not isinstance(queries, list):
        return None
    queries = [str(q).strip() for q in queries]
    if not any(queries):
        return None
    return queries[:n_steps]  # caller pads any shortfall


def split_into_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def factcheck_only(claim: str, binary: bool = False) -> dict:
    """Call 1: model-only fact-check -> plain reasoning bullets + verdict (no queries)."""
    prompt = build_factcheck_prompt(claim, binary=binary)
    resp = call_glm(prompt)

    data = parse_factcheck_json(resp.content)
    if data is None:
        repair_resp = call_glm(prompt + REPAIR_SUFFIX)
        data = parse_factcheck_json(repair_resp.content)
        if data is not None:
            resp = repair_resp
    parse_ok = data is not None

    if parse_ok:
        steps = data["reasoning_steps"]
        raw_verdict = data["verdict"]
    else:
        steps = split_into_sentences(resp.content) or split_into_sentences(resp.thinking)
        raw_verdict = resp.content

    verdict, verdict_parse_ok = parse_label(
        raw_verdict if parse_ok else resp.content,
        labels=BINARY_LABELS if binary else OFFICIAL_LABELS,
    )

    return {
        "verdict": verdict,
        "verdict_parse_ok": verdict_parse_ok,
        "parse_ok": parse_ok,
        "steps": steps,
        "thinking": resp.thinking,
        "raw_content": resp.content,
        "latency_ms": resp.latency_ms,
    }


def generate_queries(claim: str, steps: list[str]) -> list[str]:
    """Call 2: one web-search query per reasoning step. Falls back to the step text itself."""
    if not steps:
        return []
    prompt = build_query_prompt(claim, steps)
    resp = call_glm(prompt)
    queries = parse_query_json(resp.content, len(steps))
    if queries is None:
        repair_resp = call_glm(prompt + REPAIR_SUFFIX)
        queries = parse_query_json(repair_resp.content, len(steps))
    if queries is None:
        queries = []
    # Pad any shortfall (parse failure or too-few queries) with the step text.
    return [queries[i] if i < len(queries) and queries[i] else steps[i]
            for i in range(len(steps))]


def factcheck_and_bulletize(claim: str, binary: bool = False) -> dict:
    """Two calls: fact-check (reasoning bullets + verdict), then per-bullet query generation.
    Returns evidence as [{statement, search_query}] for downstream compatibility."""
    fc = factcheck_only(claim, binary=binary)
    queries = generate_queries(claim, fc["steps"])
    evidence = [{"statement": s, "search_query": q} for s, q in zip(fc["steps"], queries)]
    return {
        "verdict": fc["verdict"],
        "verdict_parse_ok": fc["verdict_parse_ok"],
        "parse_ok": fc["parse_ok"],
        "reasoning_steps": fc["steps"],
        "thinking": fc["thinking"],
        "raw_content": fc["raw_content"],
        "evidence": evidence,
        "latency_ms": fc["latency_ms"],
    }


def load_gold_urls(resources_dir: Path, claim_id: int) -> set[str]:
    path = resources_dir / f"{claim_id}.json"
    gold = set()
    if not path.exists():
        return gold
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            if doc.get("type") == "gold" and doc.get("url"):
                gold.add(doc["url"])
    return gold


def retrieve_with_scores(kb: KnowledgeBase, query: str, top_k: int) -> list[dict]:
    """Runs kNN retrieval directly (kb._call_api discards distances)."""
    knn = kb.embedding_knns.get(kb.current_claim_id)
    if knn is None:
        return []

    query_embedding = kb._embed(query).reshape(1, -1)
    k = min(top_k, knn.n_samples_fit_)
    if k == 0:
        return []

    distances, indices = knn.kneighbors(query_embedding, k)

    rows = []
    for rank, (idx, dist) in enumerate(zip(indices[0], distances[0])):
        url, text, _ = kb.retrieve(int(idx))
        rows.append({
            "rank": rank,
            "url": url,
            "distance": float(dist),
            "snippet": text[:300],
        })
    return rows


def clamp_range(start: int, n: int, max_claims: int) -> tuple[int, int]:
    if start < 0:
        start = 0
    if start >= max_claims:
        sys.exit(f"--start ({start}) is >= the KB's max claim count ({max_claims}).")
    if start + n > max_claims:
        clipped = max_claims - start
        print(f"[warn] --start {start} --n {n} exceeds {max_claims} available claims; "
              f"clipping n to {clipped}.")
        n = clipped
    return start, n


def load_existing_claim_ids(jsonl_path: Path) -> set[int]:
    if not jsonl_path.exists():
        return set()
    ids = set()
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ids.add(json.loads(line)["claim_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--variant", type=str, default="dev")
    parser.add_argument("--data", type=str,
                         default=str(DEFAME_DIR / "data" / "AVeriTeC" / "dev.json"))
    parser.add_argument("--out", type=str,
                         default=str(REPO_ROOT / "experiments" / "runs" / "01_deepseek_10claim"))
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--binary", action="store_true",
                         help="Restrict the model-only verdict to Supported/Refuted only")
    args = parser.parse_args()

    # cwd is permanently DEFAME_DIR (see KB import above), so resolve any
    # relative --data/--out the user passed against the ORIGINAL launch dir.
    if not os.path.isabs(args.data):
        args.data = os.path.join(_original_cwd, args.data)
    if not os.path.isabs(args.out):
        args.out = os.path.join(_original_cwd, args.out)

    if args.model:
        os.environ["MODEL_NAME"] = args.model
    if "MODEL_NAME" not in os.environ:
        sys.exit("MODEL_NAME not set (pass --model or set it in baseline/.env)")
    if "OPENROUTER_API_KEY" not in os.environ:
        sys.exit("OPENROUTER_API_KEY not set (set it in baseline/.env)")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "evidence_rag.jsonl"
    csv_path = out_dir / "evidence_rag_docs.csv"
    summary_path = out_dir / "evidence_rag_summary.json"

    print(f"Loading claims from {args.data} ...")
    with open(args.data) as f:
        claims = json.load(f)

    print(f"Loading KnowledgeBase(variant={args.variant!r}, device={args.device!r}) ...")
    kb = KnowledgeBase(variant=args.variant, logger=None, device=args.device)
    print(f"KB restored: {len(kb.embedding_knns)} claim indices available "
          f"(sample keys: {sorted(list(kb.embedding_knns.keys()))[:5]})")

    start, n = clamp_range(args.start, args.n, len(kb.embedding_knns))
    claim_ids = list(range(start, start + n))

    resources_dir = DEFAME_DIR / "data" / "AVeriTeC" / "knowledge_base" / args.variant / "resources"

    existing_ids = load_existing_claim_ids(jsonl_path) if args.resume else set()
    if existing_ids:
        print(f"Resuming: {len(existing_ids)} claim(s) already in {jsonl_path}, skipping those.")

    csv_is_new = not csv_path.exists()
    jsonl_f = open(jsonl_path, "a")
    csv_f = open(csv_path, "a")
    csv_fields = ["claim_id", "claim", "gold_label", "predicted_verdict", "parse_ok",
                  "evidence_idx", "evidence_statement", "search_query",
                  "doc_rank", "doc_url", "doc_distance", "is_gold", "doc_snippet"]
    if csv_is_new:
        csv_f.write(",".join(csv_fields) + "\n")

    def csv_escape(value) -> str:
        s = "" if value is None else str(value)
        s = s.replace('"', '""')
        return f'"{s}"'

    for claim_id in claim_ids:
        if claim_id in existing_ids:
            continue
        if claim_id not in kb.embedding_knns or kb.embedding_knns[claim_id] is None:
            print(f"[skip] claim {claim_id}: no KB resources for this claim")
            continue

        record = claims[claim_id]
        claim_text = record["claim"]
        gold_label = record.get("label")

        print(f"[{claim_id}] fact-checking + bulletizing evidence ...")
        t0 = time.perf_counter()
        result = factcheck_and_bulletize(claim_text, binary=args.binary)
        print(f"[{claim_id}] verdict={result['verdict']!r} "
              f"parse_ok={result['parse_ok']} n_evidence={len(result['evidence'])} "
              f"({time.perf_counter() - t0:.1f}s)")

        kb.current_claim_id = claim_id
        gold_urls = load_gold_urls(resources_dir, claim_id)

        evidence_out = []
        for evidence_idx, ev in enumerate(result["evidence"]):
            docs = retrieve_with_scores(kb, ev["search_query"], args.top_k)
            for doc in docs:
                doc["is_gold"] = doc["url"] in gold_urls
            evidence_out.append({
                "statement": ev["statement"],
                "search_query": ev["search_query"],
                "docs": docs,
            })

            if docs:
                for doc in docs:
                    row = [
                        claim_id, claim_text, gold_label, result["verdict"], result["parse_ok"],
                        evidence_idx, ev["statement"], ev["search_query"],
                        doc["rank"], doc["url"], doc["distance"], doc["is_gold"], doc["snippet"],
                    ]
                    csv_f.write(",".join(csv_escape(v) for v in row) + "\n")
            else:
                row = [
                    claim_id, claim_text, gold_label, result["verdict"], result["parse_ok"],
                    evidence_idx, ev["statement"], ev["search_query"],
                    "", "", "", "", "",
                ]
                csv_f.write(",".join(csv_escape(v) for v in row) + "\n")

        jsonl_record = {
            "claim_id": claim_id,
            "claim": claim_text,
            "gold_label": gold_label,
            "predicted_verdict": result["verdict"],
            "verdict_parse_ok": result["verdict_parse_ok"],
            "parse_ok": result["parse_ok"],
            "reasoning_steps": result["reasoning_steps"],
            "thinking": result["thinking"],
            "latency_ms": result["latency_ms"],
            "evidence": evidence_out,
        }
        jsonl_f.write(json.dumps(jsonl_record) + "\n")
        jsonl_f.flush()
        csv_f.flush()

    jsonl_f.close()
    csv_f.close()

    print(f"Wrote {jsonl_path} and {csv_path}")
    write_summary(jsonl_path, summary_path)
    print(f"Wrote {summary_path}")


def write_summary(jsonl_path: Path, summary_path: Path) -> None:
    if not jsonl_path.exists():
        return

    n_claims = 0
    n_evidence_total = 0
    docs_per_evidence = []
    all_distances = []
    gold_distances = []
    nongold_distances = []
    parse_fail = 0

    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            n_claims += 1
            if not rec["parse_ok"]:
                parse_fail += 1
            for ev in rec["evidence"]:
                n_evidence_total += 1
                docs_per_evidence.append(len(ev["docs"]))
                for doc in ev["docs"]:
                    all_distances.append(doc["distance"])
                    (gold_distances if doc["is_gold"] else nongold_distances).append(doc["distance"])

    def dist_stats(values: list[float]) -> dict:
        if not values:
            return {"n": 0}
        sorted_vals = sorted(values)
        return {
            "n": len(values),
            "min": sorted_vals[0],
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "p90": sorted_vals[int(0.9 * (len(sorted_vals) - 1))],
        }

    summary = {
        "n_claims": n_claims,
        "n_evidence_total": n_evidence_total,
        "avg_evidence_per_claim": n_evidence_total / n_claims if n_claims else 0,
        "avg_docs_per_evidence": statistics.mean(docs_per_evidence) if docs_per_evidence else 0,
        "distance_stats_all": dist_stats(all_distances),
        "distance_stats_gold": dist_stats(gold_distances),
        "distance_stats_nongold": dist_stats(nongold_distances),
        "parse_fail_count": parse_fail,
    }

    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
