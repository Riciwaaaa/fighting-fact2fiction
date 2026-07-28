"""
Phase 1: run clean (un-poisoned) InFact for the 47 new claims.

The Fact2Fiction attack REQUIRES a pre-attack InFact report at
  Fact2Fiction/src/fc_results/infact/<fc_model>/search_top_five/docs/{cid}
because it fabricates evidence targeting that report's sub-questions and verdict
(attack/main.py:671-681). The legacy 53 claims already have these; the 47 new
claims do not. This script produces them.

Those cache files are just DEFAME's `infact.eval.evaluate.evaluate()` output docs
(out/.../docs/{cid}.md) with the `.md` extension stripped. We reproduce the exact
config that generated the existing mimo clean reports (from that run's config.yaml:
procedure_variant=infact, max_iterations=3, max_result_len=64000, llm_kwargs={}),
but with the `averitec_binary` benchmark so the Judge's label space is Supported/
Refuted only -- this makes every clean verdict a well-defined inversion target for
the attack (an NEI clean verdict would have no opposite to flip to).

`clean_infact` is now defined as InFact's verdict on the un-poisoned KB, whatever it
is (not necessarily gold) -- so wrong clean verdicts here are expected and kept.

Idempotent: claims that already have an fc_results doc are skipped. Must run under
/home/ubuntu/.venv312/bin/python3.12, in the DEFAME env (never alongside the
Fact2Fiction `infact` copy).
"""

import argparse
import json
import os
import sys
from multiprocessing import set_start_method
from pathlib import Path

try:
    import torch  # noqa: F401
except ImportError:
    sys.exit("Run with /home/ubuntu/.venv312/bin/python3.12 (needs torch/sklearn).")

from fusion_common import DEFAME_DIR, DEFAULT_RUN_DIR, F2F_SRC, load_manifest

CLEAN_DOCS_REL = "fc_results/infact/{fc_model}/search_top_five/docs"


def clean_doc_path(fc_model: str, cid: int) -> Path:
    return F2F_SRC / CLEAN_DOCS_REL.format(fc_model=fc_model) / str(cid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=str, default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--claims", type=str, default=None,
                        help="Comma-separated override; default = new_claim_ids from the manifest")
    parser.add_argument("--fc-model", type=str, default=None,
                        help="Fact-checker model shorthand; default from the manifest")
    parser.add_argument("--variant", type=str, default="dev")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    manifest = load_manifest(run_dir)
    fc_model = args.fc_model or manifest["fc_model"]

    if args.claims:
        target_ids = [int(x) for x in args.claims.split(",")]
    else:
        target_ids = list(manifest["new_claim_ids"])

    # Only run claims that still lack a clean report on disk.
    dst_dir = clean_doc_path(fc_model, 0).parent
    dst_dir.mkdir(parents=True, exist_ok=True)
    todo = [cid for cid in target_ids if not clean_doc_path(fc_model, cid).exists()]
    print(f"Clean InFact: {len(target_ids)} requested, {len(target_ids) - len(todo)} "
          f"already cached, {len(todo)} to run.")
    if not todo:
        print("Nothing to do.")
        return

    os.chdir(DEFAME_DIR)
    sys.path.insert(0, str(DEFAME_DIR))
    set_start_method("spawn")

    from infact.eval.evaluate import evaluate

    # Snapshot existing output dirs so we can locate the fresh one afterward.
    out_root = DEFAME_DIR / "out" / "averitec_binary" / "infact" / fc_model
    before = set(out_root.glob("*")) if out_root.exists() else set()

    evaluate(
        llm=fc_model,
        tools_config=dict(searcher=dict(
            search_engine_config=dict(averitec_kb=dict(variant=args.variant)),
            limit_per_search=5,
        )),
        fact_checker_kwargs=dict(
            procedure_variant="infact",
            max_iterations=3,
            max_result_len=64_000,
        ),
        llm_kwargs={},
        benchmark_name="averitec_binary",
        benchmark_kwargs=dict(variant=args.variant),
        sample_ids=todo,
        random_sampling=False,
        print_log_level="info",
        n_workers=1,
    )

    # Locate the run's output docs dir (the newest dir not present before).
    after = set(out_root.glob("*"))
    fresh = sorted(after - before, key=lambda p: p.stat().st_mtime)
    if not fresh:
        # Fallback: pick the most recently modified dir.
        fresh = sorted(after, key=lambda p: p.stat().st_mtime)
    docs_src = fresh[-1] / "docs"
    print(f"Reading docs from {docs_src}")

    n_ok, n_bad = 0, 0
    for cid in todo:
        src = docs_src / f"{cid}.md"
        if not src.exists():
            print(f"[{cid}] no output doc produced -> SKIP", flush=True)
            n_bad += 1
            continue
        text = src.read_text()
        if "### Verdict:" not in text:
            print(f"[{cid}] doc has no '### Verdict:' -> SKIP (malformed)", flush=True)
            n_bad += 1
            continue
        dst = clean_doc_path(fc_model, cid)
        dst.write_text(text)
        n_ok += 1

    print(f"Clean InFact done: {n_ok} reports written, {n_bad} missing/malformed. "
          f"Cache dir: {dst_dir}")
    if n_bad:
        print("WARNING: re-run this script to retry the missing claims before Phase 2.")


if __name__ == "__main__":
    main()
