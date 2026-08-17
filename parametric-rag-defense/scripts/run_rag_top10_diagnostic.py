#!/usr/bin/env python3
"""Run the frozen top-10-per-subquestion RAG diagnostic on opened confirmation rows."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from parametric_rag_defense.averitec import atomic_json
from parametric_rag_defense.matrix import build_rag_tasks
from run_stage1_rag_scan import ScanRunner


class Top10DiagnosticRunner(ScanRunner):
    """Reuse frozen plans/poison while changing only the retrieved evidence budget."""

    def __init__(self, args: argparse.Namespace):
        super().__init__(args)
        if self.config.get("status") != "frozen_before_rag_top10_diagnostic_inference":
            raise ValueError("top-10 diagnostic configuration is not frozen")
        if self.retrieval_top_k != 10:
            raise ValueError("this diagnostic requires retrieval_top_k=10")
        reuse = self.config["diagnostic_reuse"]
        self.source_config_path = Path(reuse["source_config"])
        self.source_config = json.loads(self.source_config_path.read_text(encoding="utf-8"))
        self.source_trace_root = Path(reuse["source_trace_root"])
        self.source_poison_root = Path(reuse["source_poison_root"])
        self.frozen_eligibility_path = Path(reuse["frozen_eligibility"])
        self.attack_scope_path = self.evaluation_root / "frozen_top5_attack_scope.json"

        source_tasks = build_rag_tasks(
            self.source_config,
            reuse["source_tier"],
            self.claim_ids,
        )
        enabled = {model["id"] for model in self.models}
        self.source_clean_tasks = {
            (task["model_id"], int(task["claim_id"])): task
            for task in source_tasks
            if task["model_id"] in enabled and task["condition"]["id"] == "clean"
        }

    def source_trace(self, model_id: str, claim_id: int) -> dict[str, Any]:
        task = self.source_clean_tasks[(model_id, claim_id)]
        path = self.source_trace_root / task["task_key"][:2] / f"{task['task_key']}.json"
        trace = json.loads(path.read_text(encoding="utf-8"))
        if trace.get("task_key") != task["task_key"]:
            raise ValueError(f"source trace key mismatch: {model_id}/{claim_id}")
        source_task = trace.get("task", {})
        if (
            source_task.get("model_id") != model_id
            or int(source_task.get("claim_id", -1)) != claim_id
            or source_task.get("condition", {}).get("id") != "clean"
        ):
            raise ValueError(f"source trace identity mismatch: {model_id}/{claim_id}")
        return trace

    def plan(
        self, model: dict[str, Any], claim_id: int
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        trace = self.source_trace(model["id"], claim_id)
        receipts = [
            {**dict(receipt), "reused_from_original_top5_trace": True}
            for receipt in trace["llm_receipts"]["plan"]
        ]
        return dict(trace["plan"]), receipts

    def poison_material(self, model_id: str, claim_id: int) -> tuple[list[dict[str, Any]], Any]:
        path = self.source_poison_root / model_id / f"{claim_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        embeddings = np.load(path.with_suffix(".npy"), mmap_mode="r")
        if len(record["documents"]) != embeddings.shape[0]:
            raise RuntimeError(f"source poison text/embedding mismatch: {model_id}/{claim_id}")
        return record["documents"], embeddings

    def clean_eligibility(self) -> dict[str, Any]:
        # Retain top-10 clean predictions for utility reporting, but never use them to change the
        # attacked scope. The original top-5 eligibility is the matched comparison population.
        observed = super().clean_eligibility()
        source = json.loads(self.frozen_eligibility_path.read_text(encoding="utf-8"))
        expected_models = {model["id"] for model in self.models}
        if not expected_models <= set(source.get("models", {})):
            raise ValueError("frozen eligibility is missing a selected model")
        active_claims = set(self.claim_ids)
        models: dict[str, Any] = {}
        for model_id in sorted(expected_models):
            value = source["models"][model_id]
            if value.get("missing_claim_ids"):
                raise ValueError(f"source eligibility is incomplete for {model_id}")
            eligible = [
                int(claim_id)
                for claim_id in value["eligible_claim_ids"]
                if int(claim_id) in active_claims
            ]
            models[model_id] = {
                **value,
                "eligible_claim_ids": eligible,
                "clean_correct_count": len(eligible),
                "missing_claim_ids": [],
                "top10_clean_correct_count": observed["models"][model_id][
                    "clean_correct_count"
                ],
                "top10_clean_accuracy": observed["models"][model_id]["clean_accuracy"],
            }
        scope = {
            "evaluation_schema_version": 1,
            "status": "frozen_top5_eligibility_reused_for_top10_diagnostic",
            "source_path": str(self.frozen_eligibility_path),
            "source_sha256": hashlib.sha256(
                self.frozen_eligibility_path.read_bytes()
            ).hexdigest(),
            "filter": source["filter"],
            "models": models,
        }
        atomic_json(self.attack_scope_path, scope)
        self.ledger.update(
            status="running",
            phase="eligibility",
            event="frozen_top5_attack_scope_loaded",
            counts={
                "top10_clean_completed": sum(
                    value["completed"] for value in observed["models"].values()
                ),
                "frozen_eligible_pairs": sum(
                    len(value["eligible_claim_ids"]) for value in models.values()
                ),
            },
            artifacts={
                "top10_clean_eligibility": str(self.eligibility_path),
                "frozen_attack_scope": str(self.attack_scope_path),
            },
        )
        return scope

    def prepare_attacks(self, eligibility: dict[str, Any]) -> dict[str, Any]:
        successes = []
        failures = []
        for model_id, value in eligibility["models"].items():
            for claim_id in value["eligible_claim_ids"]:
                try:
                    documents, embeddings = self.poison_material(model_id, int(claim_id))
                    successes.append(
                        {
                            "model_id": model_id,
                            "claim_id": int(claim_id),
                            "documents": len(documents),
                            "embedding_rows": int(embeddings.shape[0]),
                            "reused": True,
                        }
                    )
                except Exception as exc:  # preserve resumable manifest instead of hiding a hole
                    failures.append(
                        {
                            "model_id": model_id,
                            "claim_id": int(claim_id),
                            "error": repr(exc),
                        }
                    )
        manifest_path = self.workflow_root / "reused_attack_plan_manifest.json"
        atomic_json(
            manifest_path,
            {
                "status": "source_poison_corpora_reused_without_generation",
                "source_root": str(self.source_poison_root),
                "requested": len(successes) + len(failures),
                "successes": successes,
                "failures": failures,
            },
        )
        self.ledger.update(
            status="running" if not failures else "failed",
            phase="attack_planning",
            event="source_poison_corpora_audited",
            counts={
                "expected": len(successes) + len(failures),
                "completed": len(successes),
                "failed": len(failures),
            },
            artifacts={"manifest": str(manifest_path)},
        )
        return {
            "requested": len(successes) + len(failures),
            "successes": successes,
            "failures": failures,
        }

    def preflight(self) -> dict[str, Any]:
        eligibility = json.loads(self.frozen_eligibility_path.read_text(encoding="utf-8"))
        plan_count = 0
        for model in self.models:
            for claim_id in self.claim_ids:
                self.source_trace(model["id"], claim_id)
                plan_count += 1
        poison_count = 0
        eligible_pairs = 0
        for model in self.models:
            selected = [
                int(value)
                for value in eligibility["models"][model["id"]]["eligible_claim_ids"]
                if int(value) in set(self.claim_ids)
            ]
            eligible_pairs += len(selected)
            for claim_id in selected:
                self.poison_material(model["id"], claim_id)
                poison_count += 1
        rates = len(self.scan_rates)
        return {
            "status": "passed",
            "retrieval_top_k": self.retrieval_top_k,
            "models": [model["id"] for model in self.models],
            "claims_per_model": len(self.claim_ids),
            "source_plans": plan_count,
            "source_poison_corpora": poison_count,
            "clean_endpoints": plan_count,
            "eligible_pairs": eligible_pairs,
            "attacked_rates": rates,
            "attacked_endpoints": eligible_pairs * rates,
            "total_endpoints": plan_count + eligible_pairs * rates,
            "cache_root": str(self.cache.root),
            "run_root": str(self.run_root),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/rag_top10_confirmation_diagnostic_v1.json"),
    )
    parser.add_argument("--phase", choices=("clean", "poison", "all"), default="all")
    parser.add_argument("--models", help="comma-separated victim model IDs")
    parser.add_argument("--claims", help="comma-separated claim IDs")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--contract-retries", type=int, default=2)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--evidence-chars", type=int, default=1800)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    if args.workers < 1 or args.contract_retries < 0 or args.evidence_chars < 200:
        raise SystemExit("invalid workers, retries, or evidence character limit")
    args.dataset = None
    args.data_root = None
    args.tier = "rag_top10_confirmation_diagnostic"
    args.artifact_label = "top10"
    args.experiment_id = "rag_top10_confirmation_v1"
    runner = Top10DiagnosticRunner(args)
    if args.preflight:
        print(json.dumps(runner.preflight(), indent=2, sort_keys=True))
        return
    runner.run()


if __name__ == "__main__":
    main()
