"""
Part 1 of the "model-knowledge supplement" experiment.

Live-reruns the Fact2Fiction-poisoned InFact fact-checker for a fixed set of
claims and dumps, per claim, the attacked verdict + the FULL structured evidence
InFact actually adopted (each with source, text, and a fake-vs-original flag).

This uses the Fact2Fiction copy of the `infact`/`config` packages, so it must run
in its own process (never in the same interpreter as the DEFAME `infact` copy used
by the orchestrator). It calls attack_single_claim() directly, bypassing
attack_all_claims (which skips claim_ids already present in the results jsonl).

The poison artifacts (fake resources + kNN indices + original embeddings) are
already cached for fc-deepseek_v4_flash_att-deepseek_v4_flash, so the attacker LLM
is NOT re-invoked; only InFact's own fact-checking LLM calls run.

Must run under /home/ubuntu/.venv312/bin/python3.12 (torch/sklearn/sentence-transformers).
"""

import argparse
import json
import os
import sys
import time
import traceback
from argparse import Namespace
from pathlib import Path

try:
    import torch  # noqa: F401
except ImportError:
    sys.exit(
        "This script requires torch. Run it with:\n"
        "  /home/ubuntu/.venv312/bin/python3.12 experiments/run_attacked_infact.py ..."
    )

REPO_ROOT = Path(__file__).resolve().parent.parent
F2F_SRC = REPO_ROOT / "Fact2Fiction" / "src"

# Default claim set: first 10 claim_ids present in BOTH the deepseek_v4_flash
# attack set and the KB (0-99).
DEFAULT_CLAIM_IDS = [0, 3, 4, 5, 7, 8, 12, 16, 19, 20]

# Fixed attack configuration (matches the cached poison artifacts on disk).
POISON_RATE = 0.08
ATTACK_TYPE = "fact2fiction"
VICTIM = "infact"
VARIANT = "dev"
ATTACKER_MODEL = "deepseek_v4_flash"
FACT_CHECKER_MODEL = "deepseek_v4_flash"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=str, default=None,
                        help="Comma-separated claim ids (default: the fixed 10-claim set)")
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--fc-model", type=str, default=FACT_CHECKER_MODEL,
                        help="Fact-checker (victim) model shorthand, e.g. mimo_v25_pro")
    parser.add_argument("--attacker-model", type=str, default=ATTACKER_MODEL,
                        help="Attacker model shorthand (must match cached poison artifacts)")
    parser.add_argument("--out", type=str,
                        default=str(REPO_ROOT / "experiments" / "runs" / "01_deepseek_10claim" / "attacked_infact_dumps"),
                        help="Directory for per-claim JSON dumps (resolved before chdir)")
    parser.add_argument("--binary", action="store_true",
                        help="Restrict the attacked InFact's re-verdict to Supported/Refuted only")
    args = parser.parse_args()

    claim_ids = ([int(x) for x in args.claims.split(",")] if args.claims
                 else list(DEFAULT_CLAIM_IDS))

    # Resolve output dir to an absolute path BEFORE we chdir into Fact2Fiction/src.
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # The attack code resolves config/ and working_dir relative to cwd, and
    # data_base_dir is an absolute path in globals, so chdir into Fact2Fiction/src.
    os.chdir(F2F_SRC)
    sys.path.insert(0, str(F2F_SRC))

    from attack.main import attack_single_claim
    from attack.attack_utils import setup_experiment_dir, setup_process_logger

    # Reuse the EXISTING experiment dir so the cached resources/knns pkls are found.
    # out_dir here is the attack's own out_dir (contains dev_fact2fiction_infact_0.08/).
    exp_args = Namespace(
        variant=VARIANT,
        attack_type=ATTACK_TYPE,
        victim=VICTIM,
        poison_rate=POISON_RATE,
        exp_name=None,  # -> dev_fact2fiction_infact_0.08
        out_dir=str(F2F_SRC / "attack" / "attack_results"),
    )
    exp_dirs = setup_experiment_dir(exp_args)
    print(f"exp_dir: {exp_dirs['exp_dir']}")
    print(f"resources_dir: {exp_dirs['resources_dir']}")

    manifest = {"succeeded": [], "failed": {}}

    for cid in claim_ids:
        dump_path = out_dir / f"{cid}.json"
        if dump_path.exists():
            print(f"[{cid}] already dumped -> skip")
            manifest["succeeded"].append(cid)
            continue

        print(f"[{cid}] running attacked InFact ...", flush=True)
        t0 = time.perf_counter()
        logger = setup_process_logger(exp_dirs["logs_dir"], cid)
        try:
            result = attack_single_claim(
                claim_id=cid,
                poison_rate=POISON_RATE,
                attack_type=ATTACK_TYPE,
                victim=VICTIM,
                variant=VARIANT,
                device=args.device,
                attack_set_dir="fc_results",
                exp_dirs=exp_dirs,
                logger=logger,
                attacker_model=args.attacker_model,
                fact_checker_model=args.fc_model,
                binary=args.binary,
            )
            with open(dump_path, "w") as f:
                json.dump(result, f, indent=2)
            dt = time.perf_counter() - t0
            print(f"[{cid}] pred={result.get('pred_label')!r} gt={result.get('gt_label')!r} "
                  f"used_fake={result.get('used_fake_evidence')} "
                  f"used_orig={result.get('used_original_evidence')} "
                  f"n_qa={len(result.get('adopted_qa_evidence', []))} ({dt:.1f}s)", flush=True)
            manifest["succeeded"].append(cid)
        except Exception as e:  # noqa: BLE001 - keep the batch going
            print(f"[{cid}] FAILED: {e}", flush=True)
            traceback.print_exc()
            manifest["failed"][str(cid)] = repr(e)

        with open(out_dir / "_manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

    print(f"Done. {len(manifest['succeeded'])} ok, {len(manifest['failed'])} failed. "
          f"Dumps in {out_dir}")


if __name__ == "__main__":
    main()
