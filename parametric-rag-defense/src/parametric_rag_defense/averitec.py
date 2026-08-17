"""Selected-claim AVeriTeC knowledge-store preparation and semantic retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable, Sequence

EMBEDDING_MODEL = "Alibaba-NLP/gte-base-en-v1.5"
EMBEDDING_MODEL_REVISION = "a829fd0e060bb84554da0dfd354d0de0f7712b7f"
EMBEDDING_CODE_REVISION = "40ced75c3017eb27626c9d4ea981bde21a2662f4"
EMBEDDING_INPUT_CHARS = 32_000


class KnowledgeStoreError(RuntimeError):
    """Raised when the official knowledge store is absent or malformed."""


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def poison_document_count(clean_documents: int, rate: float) -> int:
    """Apply the released Fact2Fiction integer convention exactly."""

    if clean_documents < 1:
        raise ValueError("clean_documents must be positive")
    if not 0 < rate < 1:
        raise ValueError("rate must be strictly between zero and one")
    return max(1, int(clean_documents * rate / (1 - rate)))


def realized_poison_fraction(clean_documents: int, poison_documents: int) -> float:
    return poison_documents / (clean_documents + poison_documents)


def _archive_member_map(archive: zipfile.ZipFile) -> dict[int, str]:
    result: dict[int, str] = {}
    for name in archive.namelist():
        path = Path(name)
        if path.suffix != ".json" or not path.stem.isdigit():
            continue
        claim_id = int(path.stem)
        if claim_id in result:
            raise KnowledgeStoreError(f"duplicate resource member for claim {claim_id}")
        result[claim_id] = name
    return result


def extract_selected_resources(
    archive_path: Path,
    resources_root: Path,
    claim_ids: Iterable[int],
) -> dict[str, Any]:
    """Extract only selected claim JSONL files from the official 11.5 GB archive."""

    requested = sorted(set(int(value) for value in claim_ids))
    if not archive_path.exists():
        raise KnowledgeStoreError(f"knowledge-store archive not found: {archive_path}")
    resources_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        members = _archive_member_map(archive)
        missing = sorted(set(requested) - set(members))
        if missing:
            raise KnowledgeStoreError(f"archive is missing selected claims: {missing}")
        for claim_id in requested:
            destination = resources_root / f"{claim_id}.json"
            payload = archive.read(members[claim_id])
            if destination.exists():
                if destination.read_bytes() != payload:
                    raise KnowledgeStoreError(f"refusing to overwrite changed resource: {destination}")
                continue
            destination.write_bytes(payload)
    counts = {str(claim_id): len(read_resources(resources_root / f"{claim_id}.json")) for claim_id in requested}
    return {
        "source": str(archive_path.resolve()),
        "source_size_bytes": archive_path.stat().st_size,
        "claim_ids": requested,
        "claim_count": len(requested),
        "clean_document_counts": counts,
    }


def read_resources(path: Path) -> list[dict[str, Any]]:
    """Read and normalize an official per-claim resource JSONL file."""

    resources: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not value:
                continue
            if not isinstance(value, dict):
                raise KnowledgeStoreError(f"{path}:{line_number}: resource must be an object")
            text = value.get("url2text")
            if isinstance(text, list):
                text = "\n".join(str(part) for part in text)
            if not isinstance(text, str) or not text.strip():
                continue
            resources.append(
                {
                    "document_id": f"clean:{len(resources)}",
                    "text": text.strip(),
                    "is_poison": False,
                }
            )
    if not resources:
        raise KnowledgeStoreError(f"no usable resources in {path}")
    return resources


def build_selected_indexes(
    resources_root: Path,
    index_root: Path,
    claim_ids: Sequence[int],
    *,
    model_name: str = EMBEDDING_MODEL,
    device: str | None = None,
    batch_size: int = 64,
) -> dict[str, Any]:
    """Embed selected pools with the model used by the Fact2Fiction release."""

    import numpy as np
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        model_name,
        revision=EMBEDDING_MODEL_REVISION,
        trust_remote_code=True,
        device=device,
        model_kwargs={"code_revision": EMBEDDING_CODE_REVISION},
    )
    index_root.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    dimensions: set[int] = set()
    for claim_id in claim_ids:
        resources = read_resources(resources_root / f"{claim_id}.json")
        output = index_root / f"{claim_id}.npy"
        if output.exists():
            embeddings = np.load(output, mmap_mode="r")
            if embeddings.shape[0] != len(resources):
                raise KnowledgeStoreError(f"index/resource count mismatch for claim {claim_id}")
        else:
            texts = [resource["text"][:EMBEDDING_INPUT_CHARS] for resource in resources]
            embeddings = model.encode(
                texts,
                batch_size=batch_size,
                show_progress_bar=True,
                convert_to_numpy=True,
            ).astype("float32", copy=False)
            temporary = output.with_suffix(".npy.tmp")
            with temporary.open("wb") as handle:
                np.save(handle, embeddings, allow_pickle=False)
            os.replace(temporary, output)
        counts[str(claim_id)] = len(resources)
        dimensions.add(int(embeddings.shape[1]))
        print(f"indexed claim={claim_id} documents={len(resources)} shape={tuple(embeddings.shape)}")
    if len(dimensions) != 1:
        raise KnowledgeStoreError(f"inconsistent embedding dimensions: {sorted(dimensions)}")
    return {
        "embedding_model": model_name,
        "embedding_model_revision": EMBEDDING_MODEL_REVISION,
        "embedding_code_revision": EMBEDDING_CODE_REVISION,
        "embedding_input_chars": EMBEDDING_INPUT_CHARS,
        "claim_ids": list(claim_ids),
        "clean_document_counts": counts,
        "embedding_dimension": next(iter(dimensions)),
    }


def retrieve(
    query: str,
    clean_resources: Sequence[dict[str, Any]],
    clean_embeddings: Any,
    embedder: Any,
    *,
    poison_resources: Sequence[dict[str, Any]] = (),
    poison_embeddings: Any | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Return Euclidean nearest neighbors, matching the released sklearn kNN metric."""

    import numpy as np

    query_embedding = np.asarray(
        embedder.encode([query], show_progress_bar=False, convert_to_numpy=True)[0],
        dtype="float32",
    )
    if poison_resources and poison_embeddings is None:
        poison_embeddings = embedder.encode(
            [item["text"][:1500] for item in poison_resources],
            show_progress_bar=False,
            convert_to_numpy=True,
        )
    return retrieve_embedding(
        query_embedding,
        clean_resources,
        clean_embeddings,
        poison_resources=poison_resources,
        poison_embeddings=poison_embeddings,
        top_k=top_k,
    )


def retrieve_embedding(
    query_embedding: Any,
    clean_resources: Sequence[dict[str, Any]],
    clean_embeddings: Any,
    *,
    poison_resources: Sequence[dict[str, Any]] = (),
    poison_embeddings: Any | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Retrieve from already embedded query/documents using upstream Euclidean kNN."""

    import numpy as np

    query_embedding = np.asarray(query_embedding, dtype="float32")
    embeddings = np.asarray(clean_embeddings)
    resources = list(clean_resources)
    if poison_resources:
        if poison_embeddings is None:
            raise ValueError("poison_embeddings are required for pre-embedded retrieval")
        poison_embeddings = np.asarray(poison_embeddings, dtype="float32")
        if len(poison_embeddings) != len(poison_resources):
            raise ValueError("poison resource/embedding count mismatch")
        embeddings = np.concatenate([embeddings, poison_embeddings], axis=0)
        resources.extend(poison_resources)
    distances = np.sum((embeddings - query_embedding) ** 2, axis=1)
    limit = min(top_k, len(resources))
    candidate_indices = np.argpartition(distances, limit - 1)[:limit]
    ordered = candidate_indices[np.argsort(distances[candidate_indices])]
    return [
        {
            **resources[int(index)],
            "rank": rank,
            "distance": float(distances[int(index)]),
        }
        for rank, index in enumerate(ordered, 1)
    ]


def expand_poison_blueprints(
    blueprints: Sequence[dict[str, Any]],
    count: int,
    *,
    seed: int,
) -> list[dict[str, Any]]:
    """Deterministically expand a bounded attack plan to the exact corpus-rate budget.

    This economical expansion is for the initial scan. Publication experiments should generate
    every document independently, as the upstream implementation does.
    """

    if count < 1 or not blueprints:
        raise ValueError("a positive count and at least one blueprint are required")
    weighted: list[int] = []
    for index, item in enumerate(blueprints):
        weight = item.get("weight", 1)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            weight = 1
        weighted.extend([index] * max(1, int(math.ceil(float(weight)))))
    rng = random.Random(seed)
    rng.shuffle(weighted)
    documents: list[dict[str, Any]] = []
    for document_index in range(count):
        blueprint = blueprints[weighted[document_index % len(weighted)]]
        query = str(blueprint["query"]).strip()
        body = str(blueprint["text"]).strip()
        documents.append(
            {
                "document_id": f"poison:{document_index}",
                "text": f"{query} {body}",
                "is_poison": True,
                "blueprint_index": weighted[document_index % len(weighted)],
            }
        )
    return documents
