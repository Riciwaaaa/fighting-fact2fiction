#!/usr/bin/env python3
"""Extract and index the selected Stage 1 AVeriTeC development claims."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parametric_rag_defense.averitec import (
    EMBEDDING_MODEL,
    atomic_json,
    build_selected_indexes,
    extract_selected_resources,
    sha256_file,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--archive",
        type=Path,
        default=Path("artifacts/data/averitec/dev_knowledge_store.zip"),
    )
    parser.add_argument("--data-root", type=Path, help="Defaults to data_root in config")
    parser.add_argument(
        "--split",
        help="Split-manifest key; defaults to dataset.active_split or development",
    )
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--extract-only", action="store_true")
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Reuse a previously verified extraction manifest and build/resume indexes only",
    )
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    args.split = args.split or config["dataset"].get("active_split", "development")
    split = json.loads(Path(config["dataset"]["split_manifest"]).read_text(encoding="utf-8"))
    claim_ids = list(split[args.split]["claim_ids"])
    data_root = (args.data_root or Path(config.get("data_root", "artifacts/data/averitec"))).resolve()
    archive = args.archive.resolve()
    manifest_prefix = "" if args.split == "development" else f"{args.split}_"
    extraction_manifest = data_root / f"{manifest_prefix}extraction_manifest.json"
    if args.index_only:
        if not extraction_manifest.exists():
            raise SystemExit("--index-only requires an existing extraction manifest")
        extraction = json.loads(extraction_manifest.read_text(encoding="utf-8"))
        if extraction.get("claim_ids") != claim_ids:
            raise SystemExit("existing extraction manifest does not match the active claims")
        print(f"reusing verified extraction sha256={extraction['source_sha256']}")
    else:
        extraction = extract_selected_resources(archive, data_root / "resources", claim_ids)
        extraction["source_sha256"] = sha256_file(archive)
        atomic_json(extraction_manifest, extraction)
        print(
            f"extracted/verified claims={len(claim_ids)} archive_bytes={archive.stat().st_size} "
            f"sha256={extraction['source_sha256']}"
        )
    if args.extract_only:
        return
    index = build_selected_indexes(
        data_root / "resources",
        data_root / "indexes" / "gte-base-en-v1.5",
        claim_ids,
        model_name=EMBEDDING_MODEL,
        device=args.device,
        batch_size=args.batch_size,
    )
    index["source_archive_sha256"] = extraction["source_sha256"]
    atomic_json(data_root / f"{manifest_prefix}index_manifest.json", index)
    print(
        f"indexed claims={len(claim_ids)} embedding_model={EMBEDDING_MODEL} "
        f"dimension={index['embedding_dimension']}"
    )


if __name__ == "__main__":
    main()
