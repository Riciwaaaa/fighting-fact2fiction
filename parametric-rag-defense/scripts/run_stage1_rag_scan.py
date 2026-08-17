#!/usr/bin/env python3
"""Run cached clean InFact-style endpoints and a configured Fact2Fiction rate scan."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import threading
import traceback
from pathlib import Path
from typing import Any, Callable

from parametric_rag_defense.averitec import (
    EMBEDDING_CODE_REVISION,
    EMBEDDING_MODEL,
    EMBEDDING_MODEL_REVISION,
    atomic_json,
    expand_poison_blueprints,
    poison_document_count,
    read_resources,
    realized_poison_fraction,
    retrieve_embedding,
)
from parametric_rag_defense.cache import LLMCache, LLMRequest
from parametric_rag_defense.contracts import ContractError, extract_json_object
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.labels import canonical_label
from parametric_rag_defense.matrix import build_rag_tasks, select_tier_conditions
from parametric_rag_defense.progress import ExperimentLedger
from parametric_rag_defense.providers import openai_compatible_complete
from parametric_rag_defense.rag_artifacts import artifact_path, normalize_record, store_immutable

PROMPT_FILES = {
    "plan": Path("prompts/rag_plan_v1.md"),
    "answers": Path("prompts/rag_answers_v1.md"),
    "verdict": Path("prompts/rag_verdict_v1.md"),
    "attack": Path("prompts/fact2fiction_blueprints_v1.md"),
}
UPSTREAM_PIPELINE = "InFact QA workflow, Fact2Fiction release"
UPSTREAM_SOURCE = "../fighting-fact2fiction-main/Fact2Fiction/src"
STRUCTURED_CONTRACT_VERSION = "v3-first-result-coercion"
VICTIM_EVIDENCE_CONTRACT = "neutral-source-v1"


def configured_retrieval_top_k(config: dict[str, Any]) -> int:
    """Return the explicit RAG retrieval budget while preserving historical configs."""

    value = config.get("rag_pipeline", {}).get(
        "retrieval_top_k",
        config.get("attacks", {}).get("poisonedrag", {}).get("retrieval_top_k", 5),
    )
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("rag_pipeline.retrieval_top_k must be a positive integer")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    return value.strip()


def mask_urls(value: str | None) -> str | None:
    """Replace raw URLs before victim prompts or normalized downstream artifacts."""

    if value is None:
        return None
    return re.sub(r"https?://\S*", "[URL]", value, flags=re.IGNORECASE)


def neutral_evidence_id(question_index: int, rank: int) -> str:
    """Create an origin-free identifier that reveals neither clean nor injected provenance."""

    return f"evidence_q{question_index + 1}_r{rank}"


def assert_neutral_victim_prompt(prompt: str) -> None:
    """Fail before a victim call if attack-revealing metadata reaches its message."""

    violations = []
    if re.search(r"\b(?:clean|poison):\d+\b", prompt, flags=re.IGNORECASE):
        violations.append("source-origin identifier")
    if re.search(r"https?://", prompt, flags=re.IGNORECASE):
        violations.append("raw URL")
    if violations:
        raise RuntimeError(f"victim prompt contains forbidden metadata: {', '.join(violations)}")


def parse_plan(text: str) -> dict[str, Any]:
    value = extract_json_object(text)
    if set(value) != {"questions"} or not isinstance(value["questions"], list):
        raise ContractError("plan must contain only a questions array")
    if len(value["questions"]) != 10:
        raise ContractError("plan must contain exactly 10 questions")
    questions = []
    for index, item in enumerate(value["questions"]):
        if not isinstance(item, dict) or set(item) != {"question", "query"}:
            raise ContractError(f"questions[{index}] fields are invalid")
        questions.append(
            {"question": _string(item["question"], "question"), "query": _string(item["query"], "query")}
        )
    return {"questions": questions}


def parse_answers(text: str, result_counts: list[int]) -> dict[str, Any]:
    value = extract_json_object(text)
    if set(value) != {"answers"} or not isinstance(value["answers"], list):
        raise ContractError("answer output must contain only an answers array")
    if len(value["answers"]) > len(result_counts):
        raise ContractError("answer count exceeds question count")
    by_index: dict[int, dict[str, Any]] = {}
    for item in value["answers"]:
        if not isinstance(item, dict) or set(item) != {
            "question_index", "status", "answer", "selected_rank"
        }:
            raise ContractError("answer fields are invalid")
        index = item["question_index"]
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(result_counts):
            raise ContractError("question_index is invalid")
        if index in by_index:
            raise ContractError("question_index is duplicated")
        status = item["status"]
        if status not in {"answered", "none"}:
            raise ContractError("answer status is invalid")
        answer = item["answer"]
        rank = item["selected_rank"]
        if status == "answered":
            answer = _string(answer, "answer")
            if result_counts[index] == 0:
                # Batched answering exposes other questions' evidence in the same request. Enforce
                # the upstream behavior: a question with no fresh search result is dropped rather
                # than letting the model borrow another question's evidence.
                by_index[index] = {
                    "question_index": index,
                    "status": "none",
                    "answer": None,
                    "selected_rank": None,
                }
                continue
            if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= result_counts[index]:
                # The released loop adopts the first result that produces an answer. Preserve that
                # fallback when a batched model gives an answer but omits/misstates attribution.
                rank = 1
        elif answer is not None or rank is not None:
            raise ContractError("none answers require null answer and rank")
        by_index[index] = {
            "question_index": index,
            "status": status,
            "answer": answer,
            "selected_rank": rank,
        }
    # A missing item is not evidence. Conservatively retain the requested question with a null
    # answer instead of inventing content or dropping the entire endpoint after all retries.
    for index in range(len(result_counts)):
        by_index.setdefault(
            index,
            {
                "question_index": index,
                "status": "none",
                "answer": None,
                "selected_rank": None,
            },
        )
    return {"answers": [by_index[index] for index in range(len(result_counts))]}


def parse_verdict(text: str) -> dict[str, Any]:
    value = extract_json_object(text)
    if set(value) != {"verdict", "confidence", "justification"}:
        raise ContractError("verdict fields are invalid")
    if value["verdict"] not in {"Supported", "Refuted"}:
        raise ContractError("verdict must be Supported or Refuted")
    confidence = value["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ContractError("confidence must be numeric")
    confidence = float(confidence)
    if not 0 <= confidence <= 1:
        raise ContractError("confidence must be in [0,1]")
    return {
        "verdict": value["verdict"],
        "confidence": confidence,
        "justification": _string(value["justification"], "justification"),
    }


def parse_blueprints(text: str, count: int, question_count: int) -> dict[str, Any]:
    value = extract_json_object(text)
    if set(value) != {"blueprints"} or not isinstance(value["blueprints"], list):
        raise ContractError("attack output must contain only a blueprints array")
    if len(value["blueprints"]) != count:
        raise ContractError(f"attack output must contain exactly {count} blueprints")
    blueprints = []
    for index, item in enumerate(value["blueprints"]):
        if not isinstance(item, dict) or set(item) != {"question_index", "query", "text", "weight"}:
            raise ContractError(f"blueprints[{index}] fields are invalid")
        question_index = item["question_index"]
        weight = item["weight"]
        if isinstance(question_index, bool) or not isinstance(question_index, int) or not 0 <= question_index < question_count:
            raise ContractError("blueprint question_index is invalid")
        if isinstance(weight, bool) or not isinstance(weight, int) or not 1 <= weight <= 10:
            raise ContractError("blueprint weight must be an integer in [1,10]")
        blueprints.append(
            {
                "question_index": question_index,
                "query": _string(item["query"], "query"),
                "text": _string(item["text"], "text"),
                "weight": weight,
            }
        )
    return {"blueprints": blueprints}


def render(template: str, replacements: dict[str, Any]) -> str:
    result = template
    for name, value in replacements.items():
        placeholder = "{{" + name + "}}"
        if placeholder not in result:
            raise ValueError(f"prompt template does not contain {placeholder}")
        result = result.replace(placeholder, str(value))
    if re.search(r"\{\{[A-Z][A-Z_]*}}", result):
        raise ValueError("prompt contains unresolved template variables")
    return result


def cached_structured_call(
    cache: LLMCache,
    model_config: dict[str, Any],
    *,
    stage: str,
    prompt_id: str,
    prompt: str,
    parser: Callable[[str], dict[str, Any]],
    temperature: float,
    top_p: float,
    max_tokens: int,
    seed: int,
    metadata: dict[str, Any],
    contract_retries: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    receipts = []
    previous_error = ""
    for attempt in range(contract_retries + 1):
        repair = "" if attempt == 0 else (
            f"\n\nFormat repair attempt {attempt}: The previous response violated the contract: "
            f"{previous_error}. Return the requested JSON contract exactly. Do not add markdown "
            "or commentary, and do not claim evidence for a question with zero shown results."
        )
        parameters = {
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "seed": seed,
            **model_config.get("request_parameters", {}),
        }
        request = LLMRequest(
            stage=stage,
            provider=model_config["provider"],
            model=model_config["model"],
            prompt_id=prompt_id,
            prompt_version=f"v1+sha256:{digest}+contract:{attempt}",
            messages=[{"role": "user", "content": prompt + repair}],
            parameters=parameters,
            response_format={"type": "json_object"},
        )

        # Migrate raw responses collected during the integration smoke test, when parser identity
        # was unnecessarily part of the provider-request key. The messages and decoding settings
        # are identical; only cache bookkeeping changes, and the raw text is reparsed below.
        if cache.load(request) is None:
            legacy_request = LLMRequest(
                stage=stage,
                provider=model_config["provider"],
                model=model_config["model"],
                prompt_id=prompt_id,
                prompt_version=(
                    f"v1+sha256:{digest}+parser:v2-zero-result-coercion+contract:{attempt}"
                ),
                messages=request.messages,
                parameters=request.parameters,
                response_format=request.response_format,
            )
            legacy_entry = cache.load(legacy_request)
            if legacy_entry is not None:
                cache.store(
                    request,
                    legacy_entry["response"],
                    metadata={
                        **metadata,
                        "contract_attempt": attempt,
                        "migrated_from_cache_key": legacy_request.key,
                    },
                )

        def compute() -> dict[str, Any]:
            response = openai_compatible_complete(request)
            try:
                response["parsed"] = parser(response["raw_text"])
                response["contract_ok"] = True
            except ContractError as exc:
                response["parsed"] = None
                response["contract_ok"] = False
                response["contract_error"] = str(exc)
            return response

        entry, cache_hit = cache.get_or_compute(
            request,
            compute,
            metadata={**metadata, "contract_attempt": attempt},
        )
        try:
            current_parsed = parser(entry["response"]["raw_text"])
            current_contract_ok = True
            current_contract_error = None
        except ContractError as exc:
            current_parsed = None
            current_contract_ok = False
            current_contract_error = str(exc)
        receipts.append(
            {
                "cache_key": request.key,
                "cache_hit": cache_hit,
                "stored_contract_ok": bool(entry["response"].get("contract_ok")),
                "contract_ok": current_contract_ok,
                "contract_error": current_contract_error,
                "structured_contract_version": STRUCTURED_CONTRACT_VERSION,
                "usage": entry["response"].get("usage", {}),
                "latency_ms": entry["response"].get("latency_ms"),
            }
        )
        if current_contract_ok:
            assert current_parsed is not None
            return current_parsed, receipts
        previous_error = str(current_contract_error or "unknown violation")
    raise ContractError(f"{stage} failed its output contract after {contract_retries + 1} attempts")


class ScanRunner:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.config_path = args.config.resolve()
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.retrieval_top_k = configured_retrieval_top_k(self.config)
        load_dotenv(self.config_path.parent.parent / ".env")
        dataset_path = args.dataset or Path(self.config["dataset"]["source"])
        self.dataset = json.loads(dataset_path.resolve().read_text(encoding="utf-8"))
        split = json.loads(Path(self.config["dataset"]["split_manifest"]).read_text(encoding="utf-8"))
        self.active_split = self.config["dataset"].get("active_split", "development")
        self.claim_ids = list(split[self.active_split]["claim_ids"])
        if args.claims:
            selected_claims = {int(value) for value in args.claims.split(",")}
            self.claim_ids = [value for value in self.claim_ids if value in selected_claims]
        self.models = [
            model for model in self.config["models"]
            if model.get("enabled", True) and "rag_victim" in model["roles"]
        ]
        if args.models:
            selected_models = set(args.models.split(","))
            self.models = [model for model in self.models if model["id"] in selected_models]
            missing = selected_models - {model["id"] for model in self.models}
            if missing:
                raise SystemExit(f"unknown or disabled RAG models: {sorted(missing)}")
        self.cache = LLMCache(Path(self.config["cache_root"]).resolve())
        self.data_root = (args.data_root or Path(self.config.get("data_root", "artifacts/data/averitec"))).resolve()
        self.resources_root = self.data_root / "resources"
        self.index_root = self.data_root / "indexes" / "gte-base-en-v1.5"
        self.study_root = Path(self.config["run_root"]).resolve() / self.active_split
        self.namespace = self.config["rag_pipeline"]["artifact_namespace"]
        self.run_root = self.study_root / "rag" / self.namespace
        self.artifact_root = self.run_root / "endpoints"
        self.trace_root = self.run_root / "private_traces"
        self.poison_root = self.run_root / "poison_corpora"
        self.workflow_root = self.run_root / "manifests"
        self.evaluation_root = Path(
            self.config.get("evaluation_root", "artifacts/evaluation")
        ).resolve()
        self.eligibility_path = self.evaluation_root / f"{self.namespace}_clean_eligibility.json"
        self.artifact_label = args.artifact_label
        self.scan_path = self.evaluation_root / (
            f"{self.namespace}_initial_scan.json"
            if self.artifact_label is None
            else f"{self.namespace}_{self.artifact_label}.json"
        )
        selected_conditions = select_tier_conditions(self.config, args.tier)
        self.scan_rates = tuple(
            float(condition["strength"])
            for condition in selected_conditions
            if condition["attack_family"] == "fact2fiction"
        )
        if not self.scan_rates:
            raise SystemExit(f"tier {args.tier!r} contains no Fact2Fiction conditions")
        if len(self.scan_rates) != len(set(self.scan_rates)):
            raise SystemExit(f"tier {args.tier!r} repeats a Fact2Fiction rate")
        # Keep the established 8% nested poison corpus intact when running a lower-rate subset.
        # New scans consume prefixes of the same immutable material and must never shrink it.
        self.poison_material_rate = max(
            max(self.scan_rates),
            *(float(rate) for rate in self.config["attacks"]["fact2fiction"]["initial_scan_fractions"]),
        )
        self.ledger = ExperimentLedger(
            Path(
                self.config.get(
                    "progress_root", Path(self.config["run_root"]).resolve().parent / "progress"
                )
            ).resolve(),
            args.experiment_id,
            description=(
                f"Metadata-neutral Fact2Fiction RAG scan for tier {args.tier}: "
                f"rates={list(self.scan_rates)}"
            ),
        )
        self.prompt_templates = {
            name: path.read_text(encoding="utf-8") for name, path in PROMPT_FILES.items()
        }
        tasks = build_rag_tasks(self.config, args.tier, self.claim_ids)
        enabled_ids = {model["id"] for model in self.models}
        self.tasks = {
            (task["model_id"], task["claim_id"], task["condition"]["id"]): task
            for task in tasks if task["model_id"] in enabled_ids
        }
        self.embed_lock = threading.Lock()
        self.embedder: Any = None

    def load_embedder(self) -> None:
        from sentence_transformers import SentenceTransformer

        self.embedder = SentenceTransformer(
            EMBEDDING_MODEL,
            revision=EMBEDDING_MODEL_REVISION,
            trust_remote_code=True,
            device=self.args.device,
            model_kwargs={"code_revision": EMBEDDING_CODE_REVISION},
        )

    def claim_record(self, claim_id: int) -> str:
        item = self.dataset[claim_id]
        return (
            f"Text: {mask_urls(item['claim'])}\n"
            f"Claim date: {mask_urls(item.get('claim_date') or 'unknown')}"
        )

    def plan(self, model: dict[str, Any], claim_id: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        item = self.dataset[claim_id]
        prompt = render(
            self.prompt_templates["plan"],
            {
                "CLAIM": mask_urls(item["claim"]),
                "CLAIM_DATE": mask_urls(item.get("claim_date") or "unknown"),
            },
        )
        assert_neutral_victim_prompt(prompt)
        return cached_structured_call(
            self.cache, model,
            stage="stage1_rag_plan", prompt_id="rag_plan_v1", prompt=prompt,
            parser=parse_plan, temperature=0.01, top_p=0.7, max_tokens=2400,
            seed=11, metadata={"claim_id": claim_id, "model_id": model["id"]},
            contract_retries=self.args.contract_retries,
        )

    def retrieval(
        self,
        claim_id: int,
        plan: dict[str, Any],
        poison_documents: list[dict[str, Any]],
        poison_embeddings: Any | None,
    ) -> tuple[list[list[dict[str, Any]]], int, int]:
        import numpy as np

        resources = read_resources(self.resources_root / f"{claim_id}.json")
        clean_embeddings = np.load(self.index_root / f"{claim_id}.npy", mmap_mode="r")
        queries = [item["query"] for item in plan["questions"]]
        with self.embed_lock:
            query_embeddings = self.embedder.encode(
                queries, batch_size=32, show_progress_bar=False, convert_to_numpy=True
            )
        seen: set[str] = set()
        retrievals: list[list[dict[str, Any]]] = []
        for query_embedding in query_embeddings:
            candidates = retrieve_embedding(
                query_embedding,
                resources,
                clean_embeddings,
                poison_resources=poison_documents,
                poison_embeddings=poison_embeddings,
                top_k=self.retrieval_top_k,
            )
            fresh = [item for item in candidates if item["document_id"] not in seen]
            seen.update(item["document_id"] for item in fresh)
            retrievals.append(fresh)
        flat = [item for group in retrievals for item in group]
        return retrievals, len(flat), sum(bool(item["is_poison"]) for item in flat)

    def answer_questions(
        self,
        model: dict[str, Any],
        claim_id: int,
        plan: dict[str, Any],
        retrievals: list[list[dict[str, Any]]],
        condition_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        blocks = []
        for index, (question, results) in enumerate(zip(plan["questions"], retrievals)):
            rendered_results = [
                {
                    "rank": rank,
                    "source_id": neutral_evidence_id(index, rank),
                    "text": mask_urls(result["text"][: self.args.evidence_chars]),
                }
                for rank, result in enumerate(results, 1)
            ]
            blocks.append(
                {
                    "question_index": index,
                    "question": question["question"],
                    "results": rendered_results,
                }
            )
        prompt = render(
            self.prompt_templates["answers"],
            {
                "CLAIM_RECORD": self.claim_record(claim_id),
                "RETRIEVAL_RECORD": json.dumps(blocks, ensure_ascii=False),
            },
        )
        assert_neutral_victim_prompt(prompt)
        result_counts = [len(group) for group in retrievals]
        return cached_structured_call(
            self.cache, model,
            stage="stage1_rag_answers", prompt_id="rag_answers_v1", prompt=prompt,
            parser=lambda text: parse_answers(text, result_counts),
            temperature=0.01, top_p=0.7, max_tokens=5000, seed=11,
            metadata={"claim_id": claim_id, "model_id": model["id"], "condition_id": condition_id},
            contract_retries=self.args.contract_retries,
        )

    def final_verdict(
        self,
        model: dict[str, Any],
        claim_id: int,
        plan: dict[str, Any],
        answers: dict[str, Any],
        retrievals: list[list[dict[str, Any]]],
        condition_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        qa_record = []
        for question_index, (question, answer, results) in enumerate(
            zip(plan["questions"], answers["answers"], retrievals)
        ):
            selected = None
            if answer["selected_rank"] is not None:
                result = results[answer["selected_rank"] - 1]
                selected = {
                    "source_id": neutral_evidence_id(question_index, answer["selected_rank"]),
                    "text": mask_urls(result["text"][:1000]),
                }
            qa_record.append(
                {
                    "question": mask_urls(question["question"]),
                    "answer": mask_urls(answer["answer"]),
                    "selected_evidence": selected,
                }
            )
        prompt = render(
            self.prompt_templates["verdict"],
            {"CLAIM_RECORD": self.claim_record(claim_id), "QA_RECORD": json.dumps(qa_record, ensure_ascii=False)},
        )
        assert_neutral_victim_prompt(prompt)
        return cached_structured_call(
            self.cache, model,
            stage="stage1_rag_verdict", prompt_id="rag_verdict_v1", prompt=prompt,
            parser=parse_verdict, temperature=0.01, top_p=0.7, max_tokens=1600,
            seed=11, metadata={"claim_id": claim_id, "model_id": model["id"], "condition_id": condition_id},
            contract_retries=self.args.contract_retries,
        )

    def task_for(self, model_id: str, claim_id: int, condition_id: str) -> dict[str, Any]:
        try:
            return self.tasks[(model_id, claim_id, condition_id)]
        except KeyError as exc:
            raise RuntimeError(f"task matrix lacks {model_id}/{claim_id}/{condition_id}") from exc

    def poison_material(self, model_id: str, claim_id: int) -> tuple[list[dict[str, Any]], Any]:
        import numpy as np

        path = self.poison_root / model_id / f"{claim_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        embeddings = np.load(path.with_suffix(".npy"), mmap_mode="r")
        if len(record["documents"]) != embeddings.shape[0]:
            raise RuntimeError(f"poison text/embedding row mismatch: {model_id}/{claim_id}")
        return record["documents"], embeddings

    def execute_endpoint(
        self,
        model: dict[str, Any],
        claim_id: int,
        condition_id: str,
    ) -> dict[str, Any]:
        task = self.task_for(model["id"], claim_id, condition_id)
        existing_path = artifact_path(self.artifact_root, task["task_key"])
        if existing_path.exists():
            return {"task_key": task["task_key"], "cached_artifact": True}
        plan, plan_receipts = self.plan(model, claim_id)
        poison_documents: list[dict[str, Any]] = []
        poison_embeddings = None
        if condition_id != "clean":
            rate = float(task["condition"]["strength"])
            all_documents, all_embeddings = self.poison_material(model["id"], claim_id)
            clean_count = len(read_resources(self.resources_root / f"{claim_id}.json"))
            count = poison_document_count(clean_count, rate)
            poison_documents = all_documents[:count]
            poison_embeddings = all_embeddings[:count]
        retrievals, retrieved_total, retrieved_poison = self.retrieval(
            claim_id, plan, poison_documents, poison_embeddings
        )
        answers, answer_receipts = self.answer_questions(
            model, claim_id, plan, retrievals, condition_id
        )
        verdict, verdict_receipts = self.final_verdict(
            model, claim_id, plan, answers, retrievals, condition_id
        )
        questions = []
        for question_index, (planned, answer, results) in enumerate(
            zip(plan["questions"], answers["answers"], retrievals)
        ):
            questions.append(
                {
                    "question": mask_urls(planned["question"]),
                    "status": answer["status"],
                    "answer": mask_urls(answer["answer"]),
                    "selected_rank": answer["selected_rank"],
                    "evidence": [
                        (
                            f"[{neutral_evidence_id(question_index, rank)}] "
                            f"{mask_urls(result['text'][:300])}"
                        )
                        for rank, result in enumerate(results, 1)
                    ],
                }
            )
        clean_count = len(read_resources(self.resources_root / f"{claim_id}.json"))
        injected = len(poison_documents)
        record = {
            "task_key": task["task_key"],
            "judgment": {
                "verdict": verdict["verdict"],
                "confidence": verdict["confidence"],
                "justification": mask_urls(verdict["justification"]),
                "questions": questions,
            },
            "audit": {
                "clean_documents_before_injection": clean_count,
                "poison_documents_injected": injected,
                "realized_poison_fraction": realized_poison_fraction(clean_count, injected) if injected else 0.0,
                "retrieved_documents_total": retrieved_total,
                "retrieved_poison_documents": retrieved_poison,
            },
            "provenance": {
                "pipeline": self.config["rag_pipeline"]["id"],
                "pipeline_version": self.config["rag_pipeline"]["version"],
                "structured_contract_version": STRUCTURED_CONTRACT_VERSION,
                "victim_evidence_contract": VICTIM_EVIDENCE_CONTRACT,
                "source_identifiers": "origin-free per-question evidence IDs",
                "urls_masked_before_victim": True,
                "upstream_pipeline": UPSTREAM_PIPELINE,
                "upstream_source": UPSTREAM_SOURCE,
                "embedding_model": EMBEDDING_MODEL,
                "embedding_model_revision": EMBEDDING_MODEL_REVISION,
                "embedding_code_revision": EMBEDDING_CODE_REVISION,
                "binary_verdict": True,
                "retrieval_top_k": self.retrieval_top_k,
                "question_count": 10,
                "decoding_seed": 11,
                "llm_cache_keys": {
                    "plan": [item["cache_key"] for item in plan_receipts],
                    "answers": [item["cache_key"] for item in answer_receipts],
                    "verdict": [item["cache_key"] for item in verdict_receipts],
                },
                "attack_approximation": None if condition_id == "clean" else "12-blueprint deterministic exact-budget expansion",
            },
        }
        artifact = normalize_record(record, task)
        path, already_present = store_immutable(self.artifact_root, artifact)
        trace = {
            "trace_schema_version": 1,
            "task_key": task["task_key"],
            "task": task,
            "plan": plan,
            "answers": answers,
            "verdict": verdict,
            "retrievals": [
                [
                    {
                        "document_id": result["document_id"],
                        "is_poison": result["is_poison"],
                        "rank": rank,
                        "distance": result["distance"],
                        "text_sha256": hashlib.sha256(result["text"].encode("utf-8")).hexdigest(),
                        "text_excerpt": result["text"][: self.args.evidence_chars],
                    }
                    for rank, result in enumerate(group, 1)
                ]
                for group in retrievals
            ],
            "llm_receipts": {"plan": plan_receipts, "answers": answer_receipts, "verdict": verdict_receipts},
            "artifact_path": str(path),
        }
        atomic_json(self.trace_root / task["task_key"][:2] / f"{task['task_key']}.json", trace)
        return {"task_key": task["task_key"], "cached_artifact": already_present, "verdict": verdict["verdict"]}

    def parallel_endpoints(self, jobs: list[tuple[dict[str, Any], int, str]], phase: str) -> dict[str, Any]:
        successes = []
        failures = []
        manifest_name = (
            f"{phase}_manifest.json"
            if self.artifact_label is None
            else f"{self.artifact_label}_{phase}_manifest.json"
        )
        manifest_path = self.workflow_root / manifest_name
        self.ledger.update(
            status="running",
            phase=f"{phase}_endpoints",
            event=f"{phase}_endpoints_started",
            counts={"expected": len(jobs), "completed": 0, "failed": 0, "cached": 0},
            artifacts={"manifest": str(manifest_path)},
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.args.workers) as executor:
            future_jobs = {executor.submit(self.execute_endpoint, *job): job for job in jobs}
            for completed, future in enumerate(concurrent.futures.as_completed(future_jobs), 1):
                model, claim_id, condition_id = future_jobs[future]
                try:
                    result = future.result()
                    successes.append({"model_id": model["id"], "claim_id": claim_id, "condition_id": condition_id, **result})
                    print(
                        f"{phase} {completed}/{len(jobs)} model={model['id']} claim={claim_id} "
                        f"condition={condition_id} cached={result['cached_artifact']} verdict={result.get('verdict')}"
                    )
                except Exception as exc:
                    failures.append(
                        {
                            "model_id": model["id"], "claim_id": claim_id, "condition_id": condition_id,
                            "error": repr(exc), "traceback": traceback.format_exc(),
                        }
                    )
                    print(f"{phase} {completed}/{len(jobs)} FAILED model={model['id']} claim={claim_id} condition={condition_id}: {exc}")
                if completed % 10 == 0 or completed == len(jobs):
                    atomic_json(manifest_path, {"phase": phase, "requested": len(jobs), "successes": successes, "failures": failures})
                    self.ledger.update(
                        status="running" if not failures else "failed",
                        phase=f"{phase}_endpoints",
                        event=f"{phase}_endpoint_progress",
                        counts={
                            "expected": len(jobs),
                            "completed": len(successes),
                            "failed": len(failures),
                            "cached": sum(bool(item.get("cached_artifact")) for item in successes),
                        },
                        artifacts={"manifest": str(manifest_path)},
                    )
        return {"phase": phase, "requested": len(jobs), "successes": successes, "failures": failures}

    def clean_eligibility(self) -> dict[str, Any]:
        models: dict[str, Any] = {}
        for model in self.models:
            eligible = []
            predictions = {}
            missing = []
            for claim_id in self.claim_ids:
                task = self.task_for(model["id"], claim_id, "clean")
                path = artifact_path(self.artifact_root, task["task_key"])
                if not path.exists():
                    missing.append(claim_id)
                    continue
                artifact = json.loads(path.read_text(encoding="utf-8"))
                prediction = artifact["judgment"]["verdict"]
                gold = canonical_label(
                    self.dataset[claim_id]["label"], self.config["dataset"]["label_mapping"]
                )
                predictions[str(claim_id)] = prediction
                if prediction == gold:
                    eligible.append(claim_id)
            models[model["id"]] = {
                "requested": len(self.claim_ids),
                "completed": len(predictions),
                "clean_correct_count": len(eligible),
                "clean_accuracy": len(eligible) / len(predictions) if predictions else None,
                "eligible_claim_ids": eligible,
                "missing_claim_ids": missing,
                "predictions": predictions,
            }
        result = {
            "evaluation_schema_version": 1,
            "split": self.active_split,
            "filter": "Fact2Fiction second eligibility filter: victim clean RAG verdict equals binary gold label",
            "models": models,
        }
        atomic_json(self.eligibility_path, result)
        self.ledger.update(
            status="running",
            phase="eligibility",
            event="clean_eligibility_computed",
            counts={
                "clean_completed": sum(value["completed"] for value in models.values()),
                "eligible_pairs": sum(value["clean_correct_count"] for value in models.values()),
            },
            artifacts={"eligibility": str(self.eligibility_path)},
        )
        return result

    def generate_poison_material(
        self, model: dict[str, Any], claim_id: int
    ) -> dict[str, Any]:
        import numpy as np

        path = self.poison_root / model["id"] / f"{claim_id}.json"
        embedding_path = path.with_suffix(".npy")
        clean_task = self.task_for(model["id"], claim_id, "clean")
        clean_path = artifact_path(self.artifact_root, clean_task["task_key"])
        clean_artifact = json.loads(clean_path.read_text(encoding="utf-8"))
        clean_count = clean_artifact["audit"]["clean_documents_before_injection"]
        maximum_count = poison_document_count(clean_count, self.poison_material_rate)
        blueprint_count = min(12, maximum_count)
        target = "Refuted" if clean_artifact["judgment"]["verdict"] == "Supported" else "Supported"
        clean_report = {
            "verdict": clean_artifact["judgment"]["verdict"],
            "justification": clean_artifact["judgment"]["justification"],
            "questions": [
                {"question_index": index, "question": item["question"], "answer": item["answer"]}
                for index, item in enumerate(clean_artifact["judgment"]["questions"])
            ],
        }
        prompt = render(
            self.prompt_templates["attack"],
            {
                "BLUEPRINT_COUNT": blueprint_count,
                "CLAIM_RECORD": self.claim_record(claim_id),
                "CLEAN_REPORT": json.dumps(clean_report, ensure_ascii=False),
                "TARGET_VERDICT": target,
            },
        )
        blueprints, receipts = cached_structured_call(
            self.cache, model,
            stage="stage1_fact2fiction_blueprints", prompt_id="fact2fiction_blueprints_v1", prompt=prompt,
            parser=lambda text: parse_blueprints(text, blueprint_count, 10),
            temperature=1.0, top_p=0.95, max_tokens=5000, seed=101,
            metadata={"claim_id": claim_id, "victim_model_id": model["id"], "attack_seed": 101},
            contract_retries=self.args.contract_retries,
        )
        documents = expand_poison_blueprints(blueprints["blueprints"], maximum_count, seed=101)
        documents_sha256 = hashlib.sha256(
            json.dumps(documents, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        prior_material: dict[str, Any] | None = None
        if path.exists():
            try:
                prior_material = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                prior_material = None
        material = {
            "poison_schema_version": 1,
            "model_id": model["id"],
            "claim_id": claim_id,
            "attack_seed": 101,
            "target_verdict": target,
            "clean_document_count": clean_count,
            "maximum_nominal_rate": self.poison_material_rate,
            "maximum_poison_count": maximum_count,
            "blueprint_count": blueprint_count,
            "blueprints": blueprints["blueprints"],
            "documents": documents,
            "documents_sha256": documents_sha256,
            "llm_receipts": receipts,
            "approximation": "Generate up to 12 diverse blueprints once, expand deterministically, and use nested prefixes for four rates.",
        }
        reuse_embeddings = bool(
            embedding_path.exists()
            and prior_material
            and prior_material.get("documents_sha256") == documents_sha256
        )
        if reuse_embeddings:
            try:
                reuse_embeddings = np.load(embedding_path, mmap_mode="r").shape[0] == len(documents)
            except (OSError, ValueError):
                reuse_embeddings = False
        atomic_json(path, material)
        if not reuse_embeddings:
            with self.embed_lock:
                embeddings = self.embedder.encode(
                    [item["text"][:1500] for item in documents],
                    batch_size=64, show_progress_bar=False, convert_to_numpy=True,
                ).astype("float32", copy=False)
            temporary = embedding_path.with_suffix(".npy.tmp")
            with temporary.open("wb") as handle:
                np.save(handle, embeddings, allow_pickle=False)
            os.replace(temporary, embedding_path)
        return {"model_id": model["id"], "claim_id": claim_id, "documents": maximum_count}

    def prepare_attacks(self, eligibility: dict[str, Any]) -> dict[str, Any]:
        jobs = []
        by_id = {model["id"]: model for model in self.models}
        for model_id, result in eligibility["models"].items():
            for claim_id in result["eligible_claim_ids"]:
                jobs.append((by_id[model_id], claim_id))
        successes = []
        failures = []
        manifest_name = (
            "attack_plan_manifest.json"
            if self.artifact_label is None
            else f"{self.artifact_label}_attack_plan_manifest.json"
        )
        manifest_path = self.workflow_root / manifest_name
        self.ledger.update(
            status="running",
            phase="attack_planning",
            event="attack_planning_started",
            counts={"expected": len(jobs), "completed": 0, "failed": 0},
            artifacts={"manifest": str(manifest_path)},
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.args.workers) as executor:
            future_jobs = {executor.submit(self.generate_poison_material, *job): job for job in jobs}
            for completed, future in enumerate(concurrent.futures.as_completed(future_jobs), 1):
                model, claim_id = future_jobs[future]
                try:
                    result = future.result()
                    successes.append(result)
                    print(f"attack-plan {completed}/{len(jobs)} model={model['id']} claim={claim_id} documents={result['documents']}")
                except Exception as exc:
                    failures.append({"model_id": model["id"], "claim_id": claim_id, "error": repr(exc), "traceback": traceback.format_exc()})
                    print(f"attack-plan {completed}/{len(jobs)} FAILED model={model['id']} claim={claim_id}: {exc}")
                if completed % 10 == 0 or completed == len(jobs):
                    atomic_json(manifest_path, {"requested": len(jobs), "successes": successes, "failures": failures})
                    self.ledger.update(
                        status="running" if not failures else "failed",
                        phase="attack_planning",
                        event="attack_planning_progress",
                        counts={"expected": len(jobs), "completed": len(successes), "failed": len(failures)},
                        artifacts={"manifest": str(manifest_path)},
                    )
        return {"requested": len(jobs), "successes": successes, "failures": failures}

    def poisoning_summary(self, eligibility: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "evaluation_schema_version": 1,
            "split": self.active_split,
            "tier": self.args.tier,
            "rates": list(self.scan_rates),
            "models": {},
        }
        for model in self.models:
            eligible = eligibility["models"][model["id"]]["eligible_claim_ids"]
            levels = {}
            for rate in self.scan_rates:
                condition_id = f"fact2fiction_p{rate:g}"
                completed = 0
                correct = 0
                retrieved_poison = 0
                retrieved_total = 0
                injected = []
                realized = []
                predictions = {}
                for claim_id in eligible:
                    task = self.task_for(model["id"], claim_id, condition_id)
                    path = artifact_path(self.artifact_root, task["task_key"])
                    if not path.exists():
                        continue
                    artifact = json.loads(path.read_text(encoding="utf-8"))
                    gold = canonical_label(self.dataset[claim_id]["label"], self.config["dataset"]["label_mapping"])
                    prediction = artifact["judgment"]["verdict"]
                    completed += 1
                    correct += int(prediction == gold)
                    predictions[str(claim_id)] = prediction
                    audit = artifact["audit"]
                    retrieved_poison += audit["retrieved_poison_documents"]
                    retrieved_total += audit["retrieved_documents_total"]
                    injected.append(audit["poison_documents_injected"])
                    realized.append(audit["realized_poison_fraction"])
                levels[condition_id] = {
                    "eligible": len(eligible), "completed": completed,
                    "accuracy": correct / completed if completed else None,
                    "attack_success_rate": 1 - correct / completed if completed else None,
                    "retrieved_poison_fraction": retrieved_poison / retrieved_total if retrieved_total else None,
                    "mean_poison_documents_injected": sum(injected) / len(injected) if injected else None,
                    "mean_realized_poison_fraction": sum(realized) / len(realized) if realized else None,
                    "predictions": predictions,
                }
            summary["models"][model["id"]] = {"clean_eligible_count": len(eligible), "levels": levels}
        atomic_json(self.scan_path, summary)
        return summary

    def run(self) -> None:
        self.load_embedder()
        if self.args.phase in {"clean", "all"}:
            clean_jobs = [(model, claim_id, "clean") for model in self.models for claim_id in self.claim_ids]
            manifest = self.parallel_endpoints(clean_jobs, "clean")
            if manifest["failures"]:
                self.ledger.update(
                    status="failed", phase="clean_endpoints", event="clean_phase_failed",
                    counts={"expected": len(clean_jobs), "completed": len(manifest["successes"]), "failed": len(manifest["failures"])},
                )
                raise SystemExit(f"clean phase has {len(manifest['failures'])} failures; rerun to resume")
        eligibility = self.clean_eligibility()
        if self.args.phase in {"poison", "all"}:
            if any(result["missing_claim_ids"] for result in eligibility["models"].values()):
                raise SystemExit("clean outputs are incomplete; cannot apply clean-correct eligibility")
            attack_manifest = self.prepare_attacks(eligibility)
            if attack_manifest["failures"]:
                self.ledger.update(
                    status="failed", phase="attack_planning", event="attack_planning_failed",
                    counts={"expected": attack_manifest["requested"], "completed": len(attack_manifest["successes"]), "failed": len(attack_manifest["failures"])},
                )
                raise SystemExit(f"attack planning has {len(attack_manifest['failures'])} failures; rerun to resume")
            by_id = {model["id"]: model for model in self.models}
            poison_jobs = []
            for model_id, result in eligibility["models"].items():
                for claim_id in result["eligible_claim_ids"]:
                    for rate in self.scan_rates:
                        poison_jobs.append((by_id[model_id], claim_id, f"fact2fiction_p{rate:g}"))
            manifest = self.parallel_endpoints(poison_jobs, "poison")
            summary = self.poisoning_summary(eligibility)
            print(json.dumps(summary, indent=2, sort_keys=True))
            if manifest["failures"]:
                self.ledger.update(
                    status="failed", phase="poison_endpoints", event="poison_phase_failed",
                    counts={"expected": len(poison_jobs), "completed": len(manifest["successes"]), "failed": len(manifest["failures"])},
                )
                raise SystemExit(f"poison phase has {len(manifest['failures'])} failures; rerun to resume")
            self.ledger.update(
                status="complete",
                phase="poison_scan",
                event="rate_scan_complete",
                counts={
                    "clean_endpoints": sum(value["completed"] for value in eligibility["models"].values()),
                    "eligible_pairs": sum(value["clean_correct_count"] for value in eligibility["models"].values()),
                    "poison_endpoints": len(manifest["successes"]),
                    "failed": 0,
                },
                artifacts={"scan": str(self.scan_path), "eligibility": str(self.eligibility_path)},
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument("--dataset", type=Path, help="Defaults to dataset.source in config")
    parser.add_argument("--data-root", type=Path, help="Defaults to data_root in config")
    parser.add_argument("--phase", choices=("clean", "poison", "all"), default="all")
    parser.add_argument("--tier", default="development_sweep")
    parser.add_argument(
        "--artifact-label",
        help="safe suffix for separate manifests/evaluation output; omit for historical defaults",
    )
    parser.add_argument("--models", help="comma-separated enabled victim model IDs")
    parser.add_argument("--claims", help="comma-separated claim IDs from the active split")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--contract-retries", type=int, default=2)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--evidence-chars", type=int, default=1800)
    parser.add_argument("--experiment-id", default="stage1_rag_v1.2")
    args = parser.parse_args()
    if args.workers < 1 or args.contract_retries < 0 or args.evidence_chars < 200:
        raise SystemExit("invalid workers, retries, or evidence character limit")
    if args.artifact_label and not re.fullmatch(r"[A-Za-z0-9_.-]+", args.artifact_label):
        raise SystemExit("artifact label must contain only letters, numbers, dot, underscore, or hyphen")
    ScanRunner(args).run()


if __name__ == "__main__":
    main()
