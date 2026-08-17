#!/usr/bin/env python3
"""Run the audited clean RAG pipeline on the explicitly authorized locked split."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.matrix import build_rag_tasks
from parametric_rag_defense.progress import ExperimentLedger
from run_stage1_rag_scan import ScanRunner


class LockedScanRunner(ScanRunner):
    """Stage 1 runner with locked paths while retaining the exact RAG implementation."""

    def __init__(self, args: argparse.Namespace):
        if not args.allow_locked_test:
            raise SystemExit("Refusing to open locked_test without --allow-locked-test")
        super().__init__(args)
        split = json.loads(
            Path(self.config["dataset"]["split_manifest"]).read_text(encoding="utf-8")
        )
        self.claim_ids = list(split["locked_test"]["claim_ids"])
        if args.claims:
            selected = {int(value) for value in args.claims.split(",")}
            self.claim_ids = [claim_id for claim_id in self.claim_ids if claim_id in selected]
        self.study_root = Path(self.config["run_root"]).resolve() / "locked_test"
        self.namespace = args.namespace
        self.run_root = self.study_root / "rag" / self.namespace
        self.artifact_root = self.run_root / "endpoints"
        self.trace_root = self.run_root / "private_traces"
        self.poison_root = self.run_root / "poison_corpora"
        self.workflow_root = self.run_root / "manifests"
        self.eligibility_path = (
            Path("artifacts/evaluation").resolve()
            / f"{self.namespace}_clean_eligibility.json"
        )
        self.scan_path = (
            Path("artifacts/evaluation").resolve() / f"{self.namespace}_initial_scan.json"
        )
        self.ledger = ExperimentLedger(
            Path(self.config["run_root"]).resolve().parent / "progress",
            args.experiment_id,
            description="Authorized locked clean RAG collection and eligibility",
        )
        tasks = build_rag_tasks(self.config, "locked_strength_curve", self.claim_ids)
        enabled_ids = {model["id"] for model in self.models}
        self.tasks = {
            (task["model_id"], task["claim_id"], task["condition"]["id"]): task
            for task in tasks
            if task["model_id"] in enabled_ids
        }

    def clean_eligibility(self) -> dict[str, Any]:
        result = super().clean_eligibility()
        result["split"] = "locked_test"
        result["selection_role"] = (
            "Mechanical Fact2Fiction clean-correct eligibility only; individual gold labels are "
            "not serialized into downstream packets or prompts."
        )
        atomic_json(self.eligibility_path, result)
        return result


def locked_runner_args(args: argparse.Namespace, *, phase: str) -> argparse.Namespace:
    return argparse.Namespace(
        config=args.config,
        dataset=args.dataset,
        data_root=args.data_root,
        phase=phase,
        models=args.models,
        claims=args.claims,
        workers=args.workers,
        contract_retries=args.contract_retries,
        device=args.device,
        evidence_chars=args.evidence_chars,
        experiment_id=args.experiment_id,
        namespace=args.namespace,
        allow_locked_test=args.allow_locked_test,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("../fighting-fact2fiction-main/DEFAME/data/AVeriTeC/dev.json"),
    )
    parser.add_argument("--data-root", type=Path, default=Path("artifacts/data/averitec"))
    parser.add_argument("--models", default="glm52,llama31_70b,qwen35_35b_a3b")
    parser.add_argument("--claims")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--contract-retries", type=int, default=2)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--evidence-chars", type=int, default=1800)
    parser.add_argument("--experiment-id", default="stage1_locked_clean_confirm_v1")
    parser.add_argument("--namespace", default="stage1_locked_confirm_v1")
    parser.add_argument("--allow-locked-test", action="store_true")
    args = parser.parse_args()
    if args.workers < 1 or args.contract_retries < 0 or args.evidence_chars < 200:
        raise SystemExit("invalid workers, retries, or evidence character limit")
    LockedScanRunner(locked_runner_args(args, phase="clean")).run()


if __name__ == "__main__":
    main()
