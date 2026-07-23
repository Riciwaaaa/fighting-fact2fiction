"""
Part 3: "model-only-assisted poisoned InFact" re-verdict.

For each claim, reconstruct the exact POISONED per-claim knowledge base the attacked
InFact saw, then use the model-guided gap-lead queries (from infact_supplement.py) to
retrieve MORE evidence from that same poisoned KB (which may itself contain fakes),
turn each into an InFact-style Q&A answer, ADD it to InFact's own adopted Q&A, and
have InFact's Judge re-verdict the merged document.

This mirrors the real, post-poisoning defense setting: the system cannot reach a clean
corpus, so the supplementary retrieval runs against the poisoned KB. Whether the extra
model-guided evidence lets InFact recover is exactly what we measure.

Uses the Fact2Fiction copy of `infact`/`config`, so it must run in its own process
(never together with the DEFAME `infact` copy). Runs under /home/ubuntu/.venv312/bin/python3.12.

Inputs  (produced by the earlier steps):
  - experiments/runs/02_mimo_27claim_4class/attacked_infact_dumps/{cid}.json   (adopted_qa_evidence, pred_label)
  - experiments/runs/02_mimo_27claim_4class/infact_supplement.jsonl            (gap_leads[].{lead,search_query})
Output:
  - experiments/runs/02_mimo_27claim_4class/assisted_reverdict/{cid}.json
"""

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

try:
    import torch  # noqa: F401
    import sklearn  # noqa: F401
except ImportError:
    sys.exit("Run with /home/ubuntu/.venv312/bin/python3.12 (needs torch/sklearn/sentence-transformers).")

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
F2F_SRC = REPO_ROOT / "Fact2Fiction" / "src"
DEV_JSON = REPO_ROOT / "DEFAME" / "data" / "AVeriTeC" / "dev.json"

DEFAULT_CLAIM_IDS = [0, 3, 4, 5, 6, 8, 12, 14, 17, 19, 20, 22, 23, 25, 27, 28, 29, 30,
                     31, 35, 37, 42, 53, 77, 92, 93, 98]


def qa_block(entries: list[dict]) -> str:
    """Reproduce InFact's exact '## Initial Q&A' reasoning block."""
    parts = [f"### {e['question']}\nAnswer: {e['answer']}\n\nSource URL: {e['url']}"
             for e in entries]
    return "## Initial Q&A\n" + "\n\n".join(parts)


def load_gap_leads(supplement_jsonl: Path) -> dict:
    """claim_id -> list of {lead, search_query} from infact_supplement.jsonl."""
    leads = {}
    if not supplement_jsonl.exists():
        return leads
    with open(supplement_jsonl) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            leads[rec["claim_id"]] = [
                {"lead": gl["lead"], "search_query": gl["search_query"]}
                for gl in rec.get("gap_leads", [])
            ]
    return leads


def load_supplement_meta(supplement_jsonl: Path) -> dict:
    """claim_id -> {model_only_verdict, defense_skipped} from infact_supplement.jsonl."""
    meta = {}
    if not supplement_jsonl.exists():
        return meta
    with open(supplement_jsonl) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            meta[rec["claim_id"]] = {
                "model_only_verdict": rec.get("model_only_verdict"),
                "defense_skipped": rec.get("defense_skipped"),
            }
    return meta


def canon(label):
    """Canonicalize a label dialect (model-only AVeriTeC strings vs InFact Label.value) to
    Supported/Refuted/NEI/Conflicting so the agreement check is dialect-proof. Mirrors
    infact_supplement.canon."""
    if label is None:
        return None
    s = str(label).strip().lower()
    if not s:
        return None
    if s in ("supported", "support"):
        return "Supported"
    if s in ("refuted", "refute"):
        return "Refuted"
    if "conflict" in s or "cherry" in s:
        return "Conflicting"
    if "not enough" in s or s == "nei":
        return "NEI"
    return s


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=str, default=None)
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--fc-model", type=str, default="mimo_v25_pro")
    parser.add_argument("--attacker-model", type=str, default="deepseek_v4_flash")
    parser.add_argument("--top-k", type=int, default=5,
                        help="Docs retrieved per gap lead from the poisoned KB")
    parser.add_argument("--results-dir", type=str,
                        default=str(REPO_ROOT / "experiments" / "runs" / "02_mimo_27claim_4class"))
    parser.add_argument("--binary", action="store_true",
                        help="Restrict the re-verdict Judge to Supported/Refuted only")
    args = parser.parse_args()

    claim_ids = ([int(x) for x in args.claims.split(",")] if args.claims
                 else list(DEFAULT_CLAIM_IDS))

    # Resolve all host-side paths to absolute BEFORE we chdir into Fact2Fiction/src.
    results_dir = Path(args.results_dir).resolve()
    dumps_dir = results_dir / "attacked_infact_dumps"
    supplement_jsonl = results_dir / "infact_supplement.jsonl"
    out_dir = results_dir / "assisted_reverdict"
    out_dir.mkdir(parents=True, exist_ok=True)
    dev_json = DEV_JSON.resolve()

    with open(dev_json) as f:
        claims = json.load(f)
    gap_leads_by_cid = load_gap_leads(supplement_jsonl)
    supplement_meta = load_supplement_meta(supplement_jsonl)

    # cwd + sys.path must be Fact2Fiction/src for config/*, prompt templates, working_dir.
    os.chdir(F2F_SRC)
    sys.path.insert(0, str(F2F_SRC))
    sys.path.insert(0, str(EXPERIMENTS_DIR))  # for poisoned_kb (cwd is no longer experiments/)

    from infact.common.content import Content
    from infact.common.claim import Claim
    from infact.common.document import FCDocument
    from infact.common.label import Label
    from infact.common.logger import Logger
    from infact.common.modeling import make_model
    from infact.common.results import SearchResult
    from infact.modules.judge import Judge
    from infact.eval.benchmark import AVeriTeC, AVeriTeCBinary
    from infact.prompts.prompt import AnswerQuestion
    from infact.utils.parsing import extract_last_paragraph
    from infact.tools.search.knowledge_base import KnowledgeBase

    suffix = f"_fc-{args.fc_model}_att-{args.attacker_model}"

    benchmark_cls = AVeriTeCBinary if args.binary else AVeriTeC

    logger = Logger(print_log_level="warning")
    llm = make_model(args.fc_model, logger=logger)
    judge = Judge(llm=llm, logger=logger,
                  classes=list(benchmark_cls.class_definitions.keys()),
                  class_definitions=benchmark_cls.class_definitions,
                  extra_rules=benchmark_cls.extra_judge_rules)

    # One base KB (heavy: embedding model + 236MB index); poisoned index/resources are
    # swapped in per claim.
    print(f"Loading base KnowledgeBase (device={args.device}) ...", flush=True)
    kb = KnowledgeBase(variant="dev", device=args.device)
    print("KB loaded.", flush=True)

    # Poisoned-KB reconstruction lives in poisoned_kb.py (shared with
    # subclaim_defense.py) -- imported after the chdir above, since the KB resolves
    # its relative data paths against the cwd.
    from poisoned_kb import install_poisoned_kb as _install_poisoned_kb
    from poisoned_kb import retrieve_poisoned as _retrieve_poisoned

    def install_poisoned_kb(cid: int) -> bool:
        return _install_poisoned_kb(kb, cid, suffix)

    def retrieve_poisoned(query: str, k: int) -> list[tuple]:
        return _retrieve_poisoned(kb, query, k)

    manifest = {"succeeded": [], "failed": {}}

    for cid in claim_ids:
        out_path = out_dir / f"{cid}.json"
        if out_path.exists():
            print(f"[{cid}] already done -> skip", flush=True)
            manifest["succeeded"].append(cid)
            continue

        dump_path = dumps_dir / f"{cid}.json"
        if not dump_path.exists():
            print(f"[{cid}] no attacked dump -> skip", flush=True)
            manifest["failed"][str(cid)] = "no dump"
            continue

        t0 = time.perf_counter()
        try:
            dump = json.load(open(dump_path))
            claim_text = claims[cid]["claim"]
            orig_pred = dump.get("pred_label")

            # Fast path: if the defense was skipped upstream (model-only agreed with the poisoned
            # InFact), there is nothing to correct -> assisted verdict = InFact's original. Skip
            # KB reconstruction + both judge calls entirely.
            meta = supplement_meta.get(cid, {})
            skip = meta.get("defense_skipped")
            if skip is None:  # older supplement file without the flag: derive it
                mo = meta.get("model_only_verdict")
                skip = mo is not None and canon(mo) == canon(orig_pred)
            if skip:
                record = {
                    "claim_id": cid,
                    "claim": claim_text,
                    "gold_label": claims[cid].get("label"),
                    "orig_pred": orig_pred,
                    "reproduced_pred": orig_pred,
                    "assisted_pred": orig_pred,
                    "defense_skipped": True,
                    "n_poisoned_qa": len(dump.get("adopted_qa_evidence", [])),
                    "n_new_qa": 0,
                    "n_new_fake": 0,
                    "n_gap_leads": 0,
                    "new_qa": [],
                }
                with open(out_path, "w") as f:
                    json.dump(record, f, indent=2)
                print(f"[{cid}] SKIP defense (model_only == infact) -> assisted={orig_pred} "
                      f"({time.perf_counter() - t0:.1f}s)", flush=True)
                manifest["succeeded"].append(cid)
                with open(out_dir / "_manifest.json", "w") as f:
                    json.dump(manifest, f, indent=2)
                continue

            content = Content(text=claim_text)
            claim = Claim(text=claim_text, original_context=content)

            poisoned_qa = [
                {"question": qa.get("question"), "answer": qa.get("answer"), "url": qa.get("url")}
                for qa in dump.get("adopted_qa_evidence", [])
                if qa.get("question") and qa.get("answer")
            ]
            poisoned_urls = {qa["url"] for qa in poisoned_qa}

            # Context doc for AnswerQuestion = claim + poisoned Q&A so far.
            ctx_doc = FCDocument(claim=claim)
            if poisoned_qa:
                ctx_doc.add_reasoning(qa_block(poisoned_qa))

            if not install_poisoned_kb(cid):
                raise FileNotFoundError(f"no cached poison artifacts for claim {cid} ({suffix})")

            new_qa = []
            seen_urls = set(poisoned_urls)
            for gl in gap_leads_by_cid.get(cid, []):
                results = retrieve_poisoned(gl["search_query"], args.top_k)
                for url, text, is_fake in results:
                    if not url or url in seen_urls:
                        continue
                    prompt = AnswerQuestion(gl["lead"], SearchResult(source=url, text=text), ctx_doc)
                    resp = llm.generate(prompt, max_attempts=3)
                    if resp and "NONE" not in resp and "None" not in resp:
                        answer = extract_last_paragraph(resp)
                        if answer:
                            new_qa.append({"question": gl["lead"], "answer": answer,
                                           "url": url, "is_fake": is_fake})
                            seen_urls.add(url)
                            break  # one answer per lead (mirrors answer_question_individually)

            # Assisted (additive merge) verdict.
            merged_qa = poisoned_qa + [{"question": e["question"], "answer": e["answer"],
                                        "url": e["url"]} for e in new_qa]
            merged_doc = FCDocument(claim=claim)
            merged_doc.add_reasoning(qa_block(merged_qa) if merged_qa
                                     else "## Initial Q&A\n(no evidence)")
            assisted_label = judge.judge(merged_doc)

            # Sanity: re-judge poisoned-only Q&A -> should reproduce the attacked verdict.
            poisoned_doc = FCDocument(claim=claim)
            poisoned_doc.add_reasoning(qa_block(poisoned_qa) if poisoned_qa
                                       else "## Initial Q&A\n(no evidence)")
            reproduced_label = judge.judge(poisoned_doc)

            record = {
                "claim_id": cid,
                "claim": claim_text,
                "gold_label": claims[cid].get("label"),
                "orig_pred": orig_pred,
                "reproduced_pred": reproduced_label.value,
                "assisted_pred": assisted_label.value,
                "defense_skipped": False,
                "n_poisoned_qa": len(poisoned_qa),
                "n_new_qa": len(new_qa),
                "n_new_fake": sum(1 for e in new_qa if e["is_fake"]),
                "n_gap_leads": len(gap_leads_by_cid.get(cid, [])),
                "new_qa": new_qa,
            }
            with open(out_path, "w") as f:
                json.dump(record, f, indent=2)

            dt = time.perf_counter() - t0
            print(f"[{cid}] gold={record['gold_label']} orig={record['orig_pred']} "
                  f"reproduced={record['reproduced_pred']} assisted={record['assisted_pred']} "
                  f"| new_qa={record['n_new_qa']} (fake={record['n_new_fake']}) "
                  f"poisoned_qa={record['n_poisoned_qa']} ({dt:.1f}s)", flush=True)
            manifest["succeeded"].append(cid)
        except Exception as e:  # noqa: BLE001 - keep the batch going
            print(f"[{cid}] FAILED: {e}", flush=True)
            traceback.print_exc()
            manifest["failed"][str(cid)] = repr(e)

        with open(out_dir / "_manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

    print(f"Done. {len(manifest['succeeded'])} ok, {len(manifest['failed'])} failed. "
          f"Dumps in {out_dir}", flush=True)


if __name__ == "__main__":
    main()
