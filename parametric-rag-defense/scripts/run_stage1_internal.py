#!/usr/bin/env python3
"""Run and cache retrieval-free Stage 1 claim judgments."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from parametric_rag_defense.cache import LLMCache, LLMRequest
from parametric_rag_defense.contracts import ContractError, parse_internal_judgment
from parametric_rag_defense.env import load_dotenv
from parametric_rag_defense.providers import openai_compatible_complete


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def render_prompt(template: str, claim: str, claim_date: str | None) -> str:
    return template.replace("{{CLAIM}}", claim).replace("{{CLAIM_DATE}}", claim_date or "unknown")


def parse_response(response: dict[str, Any]) -> dict[str, Any]:
    """Attach the strict contract result without discarding a malformed provider response."""

    try:
        response["parsed"] = parse_internal_judgment(response["raw_text"])
        response["contract_ok"] = True
    except ContractError as exc:
        response["parsed"] = None
        response["contract_ok"] = False
        response["contract_error"] = str(exc)
    return response


def contract_retry_request(request: LLMRequest, attempt: int) -> LLMRequest:
    """Create an auditable format-repair request without overwriting the failed first attempt."""

    reminder = (
        f"Format-repair attempt {attempt}: Return the same independent judgment again as exactly "
        "one JSON object satisfying the requested six-field contract. In particular, each list "
        "must contain at most five strings."
    )
    return LLMRequest(
        stage=request.stage,
        provider=request.provider,
        model=request.model,
        prompt_id=request.prompt_id,
        prompt_version=f"{request.prompt_version}+contract-retry:{attempt}",
        messages=[*request.messages, {"role": "user", "content": reminder}],
        parameters=request.parameters,
        response_format=request.response_format,
    )


def merge_manifest_rows(
    previous: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    *,
    compatible: bool,
    allowed_pairs: set[tuple[int, int]],
) -> list[dict[str, Any]]:
    """Merge resumable output receipts, replacing only the same claim/seed pair."""

    merged: dict[tuple[int, int], dict[str, Any]] = {}
    if compatible and previous and not previous.get("dry_run"):
        merged.update(
            {
                (int(row["claim_id"]), int(row["seed"])): row
                for row in previous.get("outputs", [])
                if (int(row["claim_id"]), int(row["seed"])) in allowed_pairs
            }
        )
    for row in rows:
        merged[(int(row["claim_id"]), int(row["seed"]))] = row
    return [merged[key] for key in sorted(merged)]


def archive_superseded_manifest(
    manifest_path: Path,
    previous: dict[str, Any] | None,
    requested_claims: list[int],
    *,
    compatible: bool,
) -> Path | None:
    """Snapshot a superseded manifest while immutable cache entries remain untouched."""

    if not previous or (compatible and previous.get("requested_claims") == requested_claims):
        return None
    serialized = json.dumps(previous, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    archive_path = (
        manifest_path.parent
        / "history"
        / manifest_path.stem
        / f"scope-{len(previous.get('requested_claims', []))}-{digest[:16]}.json"
    )
    if not archive_path.exists():
        atomic_json(archive_path, previous)
    return archive_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stage1_matrix.json"))
    parser.add_argument(
        "--dataset",
        type=Path,
        help="Dataset JSON; defaults to dataset.source in the selected config",
    )
    parser.add_argument(
        "--split",
        help="Split-manifest key; defaults to dataset.active_split or development",
    )
    parser.add_argument(
        "--models",
        help="Optional comma-separated model IDs; default is every model with the internal role",
    )
    parser.add_argument("--claims", help="Optional comma-separated subset of IDs")
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Bounded parallel provider calls per model (default: 4)",
    )
    parser.add_argument(
        "--contract-retries",
        type=int,
        default=2,
        help="Format-only retry attempts retained under distinct cache keys (default: 2)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Build requests without provider calls")
    parser.add_argument(
        "--allow-locked-test",
        action="store_true",
        help="Required to run the locked test after prompts and roles are frozen",
    )
    parser.add_argument(
        "--allow-confirmation",
        action="store_true",
        help="Required to issue calls for a non-development confirmation split",
    )
    args = parser.parse_args()

    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if args.contract_retries < 0:
        raise SystemExit("--contract-retries cannot be negative")

    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    args.dataset = args.dataset or Path(config["dataset"]["source"])
    args.split = args.split or config["dataset"].get("active_split", "development")
    if args.split == "locked_test" and not args.allow_locked_test:
        raise SystemExit("Refusing to open locked_test without --allow-locked-test")
    if args.split not in {"development", "locked_test"} and not args.allow_confirmation:
        raise SystemExit(
            f"Refusing to open confirmation split {args.split!r} without --allow-confirmation"
        )
    load_dotenv(config_path.parent.parent / ".env")
    model_configs = [
        model
        for model in config["models"]
        if "internal" in model["roles"] and model.get("enabled", True)
    ]
    if args.models:
        selected = set(args.models.split(","))
        model_configs = [model for model in model_configs if model["id"] in selected]
        missing_models = selected - {model["id"] for model in model_configs}
        if missing_models:
            raise SystemExit(f"Unknown or non-internal model IDs: {sorted(missing_models)}")

    prompt_path = Path(config["prompt"]["path"]).resolve()
    prompt_template = prompt_path.read_text(encoding="utf-8")
    prompt_digest = hashlib.sha256(prompt_template.encode("utf-8")).hexdigest()
    prompt_lock_path = prompt_path.with_suffix(prompt_path.suffix + ".sha256")
    if prompt_lock_path.exists():
        expected_prompt_digest = prompt_lock_path.read_text(encoding="utf-8").strip().split()[0]
        if prompt_digest != expected_prompt_digest:
            raise SystemExit(
                f"Prompt digest mismatch for {prompt_path}: expected "
                f"{expected_prompt_digest}, observed {prompt_digest}. Bump the prompt version and "
                f"update {prompt_lock_path} deliberately before issuing calls."
            )
    split_manifest = json.loads(Path(config["dataset"]["split_manifest"]).read_text(encoding="utf-8"))
    claim_ids = list(split_manifest[args.split]["claim_ids"])
    if args.claims:
        requested = {int(value) for value in args.claims.split(",")}
        claim_ids = [claim_id for claim_id in claim_ids if claim_id in requested]
    claims = json.loads(args.dataset.resolve().read_text(encoding="utf-8"))

    cache = LLMCache(Path(config["cache_root"]).resolve())
    decoding = config["decoding"]["internal"]
    seeds = decoding["seeds"]
    config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()

    for model_config in model_configs:
        manifest_path = (
            Path(config["run_root"]).resolve()
            / args.split
            / "internal_endpoint"
            / f"{model_config['id']}.json"
        )
        previous_manifest = None
        if manifest_path.exists() and not args.dry_run:
            previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        compatible_previous = bool(
            previous_manifest
            and previous_manifest.get("config_sha256") == config_sha256
            and previous_manifest.get("prompt_sha256") == prompt_digest
            and previous_manifest.get("model_id") == model_config["id"]
            and previous_manifest.get("split") == args.split
        )
        archived_manifest = archive_superseded_manifest(
            manifest_path,
            previous_manifest,
            claim_ids,
            compatible=compatible_previous,
        )
        if archived_manifest:
            print(f"archived prior scope manifest: {archived_manifest}")

        manifest_rows: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        jobs: list[tuple[int, int, LLMRequest]] = []
        for claim_id in claim_ids:
            claim = claims[claim_id]["claim"]
            claim_date = claims[claim_id].get("claim_date")
            prompt = render_prompt(prompt_template, claim, claim_date)
            for seed in seeds:
                parameters = {
                    "temperature": decoding["temperature"],
                    "top_p": decoding["top_p"],
                    "max_tokens": decoding["max_tokens"],
                    "seed": seed,
                    **model_config.get("request_parameters", {}),
                }
                llm_request = LLMRequest(
                    stage="stage1_internal",
                    provider=model_config["provider"],
                    model=model_config["model"],
                    prompt_id=config["prompt"]["id"],
                    prompt_version=f"{config['prompt']['version']}+sha256:{prompt_digest}",
                    messages=[{"role": "user", "content": prompt}],
                    parameters=parameters,
                    response_format={"type": "json_object"},
                )

                if args.dry_run:
                    manifest_rows.append(
                        {
                            "claim_id": claim_id,
                            "seed": seed,
                            "cache_key": llm_request.key,
                            "dry_run": True,
                        }
                    )
                    print(
                        f"model={model_config['id']} claim={claim_id} seed={seed} "
                        f"dry_run key={llm_request.key[:12]}"
                    )
                    continue
                jobs.append((claim_id, seed, llm_request))

        if not args.dry_run:
            def execute(job: tuple[int, int, LLMRequest]) -> dict[str, Any]:
                claim_id, seed, llm_request = job
                attempt_receipts: list[dict[str, Any]] = []
                active_request = llm_request
                entry: dict[str, Any] | None = None
                cache_hit = False
                for attempt in range(args.contract_retries + 1):
                    entry, cache_hit = cache.get_or_compute(
                        active_request,
                        lambda request=active_request: parse_response(
                            openai_compatible_complete(request)
                        ),
                        metadata={
                            "claim_id": claim_id,
                            "split": args.split,
                            "role": "internal_endpoint",
                            "model_id": model_config["id"],
                            "contract_attempt": attempt,
                        },
                    )
                    attempt_receipts.append(
                        {
                            "attempt": attempt,
                            "cache_key": active_request.key,
                            "cache_hit": cache_hit,
                            "contract_ok": bool(entry["response"].get("contract_ok")),
                        }
                    )
                    if entry["response"].get("contract_ok"):
                        break
                    if attempt < args.contract_retries:
                        active_request = contract_retry_request(llm_request, attempt + 1)
                assert entry is not None
                return {
                    "claim_id": claim_id,
                    "seed": seed,
                    "cache_key": active_request.key,
                    "cache_hit": cache_hit,
                    "contract_ok": bool(entry["response"].get("contract_ok")),
                    "finish_reason": entry["response"].get("finish_reason"),
                    "contract_retry_count": len(attempt_receipts) - 1,
                    "attempts": attempt_receipts,
                }

            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
                future_jobs = {executor.submit(execute, job): job for job in jobs}
                for future in concurrent.futures.as_completed(future_jobs):
                    claim_id, seed, _ = future_jobs[future]
                    try:
                        row = future.result()
                        manifest_rows.append(row)
                        print(
                            f"model={model_config['id']} claim={claim_id} seed={seed} "
                            f"cache_hit={row['cache_hit']} contract_ok={row['contract_ok']} "
                            f"contract_retries={row['contract_retry_count']}"
                        )
                    except Exception as exc:  # keep a batch manifest without hiding failures
                        failures.append({"claim_id": claim_id, "seed": seed, "error": repr(exc)})
                        print(
                            f"model={model_config['id']} claim={claim_id} seed={seed} FAILED: {exc}"
                        )

        run_manifest = {
            "run_schema_version": 1,
            "config_path": str(config_path),
            "config_sha256": config_sha256,
            "split": args.split,
            "role": "internal_endpoint",
            "model_id": model_config["id"],
            "provider": model_config["provider"],
            "model": model_config["model"],
            "prompt_sha256": prompt_digest,
            "contract_retry_limit": args.contract_retries,
            "dry_run": args.dry_run,
            "requested_claims": claim_ids,
            "outputs": merge_manifest_rows(
                previous_manifest,
                manifest_rows,
                compatible=compatible_previous and not args.dry_run,
                allowed_pairs={
                    (claim_id, seed) for claim_id in claim_ids for seed in seeds
                },
            ),
            "failures": failures,
        }
        atomic_json(manifest_path, run_manifest)
        contract_failures = [row for row in run_manifest["outputs"] if not row.get("contract_ok")]
        print(
            f"wrote {manifest_path}; outputs={len(run_manifest['outputs'])} "
            f"call_failures={len(failures)} contract_failures={len(contract_failures)}"
        )
        if failures or contract_failures:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
