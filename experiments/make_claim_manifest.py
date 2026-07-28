"""
Phase 0: build the claim manifest for the evidence-fusion run (run 05).

Writes <run_dir>/claims.json, the single source of truth for which 100 binary
claims the pipeline runs on -- replacing the stale, duplicated DEFAULT_CLAIM_IDS
lists scattered across the old scripts.

The 100 claims are:
  - legacy_claim_ids: the 53 binary claims among dev ids 0-99 that run 03 already
    processed (reused as-is, with their cached clean reports, poison, and dumps).
    Read directly from run 03's attacked_infact_dumps/ so the set can't drift.
  - new_claim_ids: the next 47 binary (Supported/Refuted) claims in dev order from
    id 100 upward, skipping any claim with no KB resource file on disk. No "clean
    InFact answered correctly" eligibility filter -- clean_infact is now defined
    simply as InFact's verdict on the un-poisoned KB, whatever it is.

NOTE: the prebuilt KB index (embedding_knns.pckl) only covers dev claims 0-99, but
resource files exist for all 500. Selection here checks the resource FILE (present
for all binary claims in range); the per-claim KNN indices for the new claims are
built separately by build_kb_index.py before Phase 1/2. This avoids a chicken-and-egg
dependency on an index that does not yet exist for these claims.

Also bootstraps the run dir by COPYING (never moving) the 53 legacy attacked dumps
into <run_dir>/attacked_infact_dumps/ so run 03 stays reproducible.

Runs in the DEFAME env; plain python3 is fine (no torch needed here).
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from fusion_common import DEFAULT_RUN_DIR, EXPERIMENTS_DIR, REPO_ROOT, load_dev_claims

KB_RESOURCES_DIR = (REPO_ROOT / "DEFAME" / "data" / "AVeriTeC" / "knowledge_base"
                    / "dev" / "resources")

LEGACY_RUN_DIR = EXPERIMENTS_DIR / "runs" / "03_mimo_27claim_binary"
N_NEW_CLAIMS = 47
NEW_START_ID = 100


def legacy_claim_ids() -> list[int]:
    """The binary claims run 03 processed, read from its attacked dumps."""
    dumps = LEGACY_RUN_DIR / "attacked_infact_dumps"
    ids = sorted(int(p.stem) for p in dumps.glob("*.json") if p.stem.isdigit())
    if not ids:
        sys.exit(f"No legacy dumps found under {dumps}")
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=str, default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--fc-model", type=str, default="mimo_v25_pro")
    parser.add_argument("--attacker-model", type=str, default="deepseek_v4_flash")
    parser.add_argument("--model-only-model", type=str, default="xiaomi/mimo-v2.5-pro")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    dev = load_dev_claims()
    legacy = legacy_claim_ids()
    legacy_set = set(legacy)

    new_ids: list[int] = []
    i = NEW_START_ID
    while len(new_ids) < N_NEW_CLAIMS and i < len(dev):
        if (i not in legacy_set
                and dev[i]["label"] in ("Supported", "Refuted")
                and (KB_RESOURCES_DIR / f"{i}.json").exists()):
            new_ids.append(i)
        i += 1

    if len(new_ids) < N_NEW_CLAIMS:
        sys.exit(f"Only found {len(new_ids)}/{N_NEW_CLAIMS} usable new binary claims "
                 f"(exhausted dev.json at id {i}).")

    all_ids = sorted(legacy + new_ids)
    manifest = {
        "run": run_dir.name,
        "fc_model": args.fc_model,
        "attacker_model": args.attacker_model,
        "model_only_model": args.model_only_model,
        "legacy_claim_ids": legacy,
        "new_claim_ids": new_ids,
        "claim_ids": all_ids,
        "failed_attacks": [],  # populated later if a new claim's attack cannot run
    }
    manifest_path = run_dir / "claims.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    # Bootstrap: copy the legacy attacked dumps into this run (idempotent).
    dst_dumps = run_dir / "attacked_infact_dumps"
    dst_dumps.mkdir(exist_ok=True)
    src_dumps = LEGACY_RUN_DIR / "attacked_infact_dumps"
    n_copied = 0
    for cid in legacy:
        src = src_dumps / f"{cid}.json"
        dst = dst_dumps / f"{cid}.json"
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
            n_copied += 1

    from collections import Counter
    new_dist = Counter(dev[i]["label"] for i in new_ids)
    print(f"Wrote {manifest_path}")
    print(f"  legacy claims: {len(legacy)}  new claims: {len(new_ids)}  total: {len(all_ids)}")
    print(f"  new-claim gold distribution: {dict(new_dist)}")
    print(f"  new claim ids: {new_ids}")
    print(f"Copied {n_copied} legacy attacked dumps into {dst_dumps}")


if __name__ == "__main__":
    main()
