"""Build reproducible Stage 1 model/attack task matrices."""

from __future__ import annotations

import hashlib
from typing import Any, Iterable

from .cache import canonical_json


def condition_id(attack_family: str, strength: int | float) -> str:
    if strength == 0:
        return "clean"
    if attack_family == "poisonedrag":
        return f"poisonedrag_n{int(strength)}"
    if attack_family == "fact2fiction":
        return f"fact2fiction_p{strength:g}"
    raise ValueError(f"Unknown attack family: {attack_family}")


def all_attack_conditions(config: dict[str, Any]) -> list[dict[str, Any]]:
    conditions: list[dict[str, Any]] = [
        {"id": "clean", "attack_family": "none", "strength": 0, "strength_unit": "none"}
    ]
    poisonedrag = config["attacks"]["poisonedrag"]
    for strength in poisonedrag["poison_docs_per_target"]:
        if strength == 0:
            continue
        conditions.append(
            {
                "id": condition_id("poisonedrag", strength),
                "attack_family": "poisonedrag",
                "strength": strength,
                "strength_unit": "malicious_documents_per_target",
                "retrieval_top_k": poisonedrag["retrieval_top_k"],
            }
        )
    fact2fiction = config["attacks"]["fact2fiction"]
    for strength in fact2fiction["poison_corpus_fractions"]:
        if strength == 0:
            continue
        conditions.append(
            {
                "id": condition_id("fact2fiction", strength),
                "attack_family": "fact2fiction",
                "strength": strength,
                "strength_unit": "target_clean_evidence_fraction",
            }
        )
    ids = [condition["id"] for condition in conditions]
    if len(ids) != len(set(ids)):
        raise ValueError("Attack condition IDs are not unique")
    return conditions


def select_tier_conditions(config: dict[str, Any], tier_name: str) -> list[dict[str, Any]]:
    tier = config["execution_tiers"][tier_name]
    conditions = all_attack_conditions(config)
    if tier.get("all_strengths"):
        return conditions
    requested = tier.get("conditions", [])
    by_id = {condition["id"]: condition for condition in conditions}
    missing = set(requested) - set(by_id)
    if missing:
        raise ValueError(f"Unknown conditions in {tier_name}: {sorted(missing)}")
    return [by_id[name] for name in requested]


def task_key(task: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(task).encode("utf-8")).hexdigest()


def build_internal_tasks(
    config: dict[str, Any], split: str, claim_ids: Iterable[int]
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for model in config["models"]:
        if "internal" not in model["roles"]:
            continue
        for claim_id in claim_ids:
            for seed in config["decoding"]["internal"]["seeds"]:
                task = {
                    "task_schema_version": 1,
                    "task_type": "internal_endpoint",
                    "split": split,
                    "claim_id": claim_id,
                    "model_id": model["id"],
                    "provider": model["provider"],
                    "model": model["model"],
                    "decoding_seed": seed,
                }
                task["task_key"] = task_key(task)
                tasks.append(task)
    return tasks


def build_rag_tasks(
    config: dict[str, Any], tier_name: str, claim_ids: Iterable[int]
) -> list[dict[str, Any]]:
    tier = config["execution_tiers"][tier_name]
    conditions = select_tier_conditions(config, tier_name)
    tasks: list[dict[str, Any]] = []
    for model in config["models"]:
        if "rag_victim" not in model["roles"]:
            continue
        for claim_id in claim_ids:
            for condition in conditions:
                attack_seeds = [None] if condition["id"] == "clean" else tier["attack_seeds"]
                for attack_seed in attack_seeds:
                    task = {
                        "task_schema_version": 2,
                        "task_type": "rag_endpoint",
                        "rag_pipeline_id": config["rag_pipeline"]["id"],
                        "rag_pipeline_version": config["rag_pipeline"]["version"],
                        "tier": tier_name,
                        "split": tier["split"],
                        "claim_id": claim_id,
                        "model_id": model["id"],
                        "provider": model["provider"],
                        "model": model["model"],
                        "condition": condition,
                        "attack_seed": attack_seed,
                    }
                    key_basis = {key: value for key, value in task.items() if key != "tier"}
                    task["task_key"] = task_key(key_basis)
                    tasks.append(task)
    return tasks
