"""
Shared poisoned-KB reconstruction, used by both rejudge_assisted.py and
subclaim_defense.py.

Single source of truth on purpose: the KNN refit below works around a real
index-misalignment bug (see install_poisoned_kb's NOTE), and a copy-pasted second
implementation is exactly how that bug gets silently re-introduced.

Must be imported AFTER chdir into Fact2Fiction/src (the caller owns the env setup),
because retrieve() resolves the KB's relative data paths against the cwd at call time.
Run under /home/ubuntu/.venv312/bin/python3.12 (needs torch/sklearn/sentence-transformers).
"""

import glob
import hashlib
import pickle
from pathlib import Path

from sklearn.neighbors import NearestNeighbors

# Attack experiment dir, relative to Fact2Fiction/src (the caller's cwd).
EXP_REL = "attack/attack_results/dev_fact2fiction_infact_0.08"

# Refitting the KNN means re-embedding every resource for the claim (~855 docs for
# claim 4), which on CPU dominates runtime -- ~16 of that claim's 17 minutes. This
# pipeline gets re-run repeatedly while iterating, so the refit is cached to disk.
CACHE_DIR = Path("/tmp/claude-1000/poisoned_kb_cache")


def _cache_path(cid: int, suffix: str, n_resources: int) -> Path:
    key = hashlib.sha1(f"{cid}|{suffix}|{n_resources}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{cid}_{key}.pkl"


def install_poisoned_kb(kb, cid: int, suffix: str, use_cache: bool = True) -> bool:
    """Reconstruct the poisoned per-claim KB in `kb` and stash its KNN for retrieval.

    Returns False if no cached poison artifacts exist for this claim/suffix.
    """
    # NOTE: we deliberately do NOT trust the cached knns/*.pkl index alignment.
    # kb._get_resources(cid) re-filters resources via langdetect, which is not
    # seeded anywhere in this codebase -> its short-text language classification
    # can differ between process runs. The cached KNN was fit (at attack-build
    # time, in a different process) against whatever _get_resources(cid) returned
    # THEN; re-deriving "original" now and reusing that stale KNN's indices can
    # silently misalign idx -> (url, text) or go out of range. Instead we refit a
    # fresh KNN here, in-process, over the SAME resource list we index with, so
    # index alignment is guaranteed self-consistent (only the fake evidence pkl,
    # which is a plain unpickle with no reprocessing, is reused as-is).
    res_matches = glob.glob(f"{EXP_REL}/resources/{cid}_*_fact2fiction_resources{suffix}.pkl")
    if not res_matches:
        return False
    fake_evidences = pickle.load(open(res_matches[0], "rb"))
    kb.cached_resources = None
    kb.cached_resources_claim_id = None
    original = kb._get_resources(cid)
    all_resources = original + fake_evidences

    # The cache stores the KNN together with the exact resource list it was fit over,
    # so a cache hit cannot reintroduce the misalignment the refit exists to avoid.
    # (langdetect nondeterminism can change len(original) between runs, which changes
    # the cache key -> a stale entry is missed rather than wrongly reused.)
    cache_file = _cache_path(cid, suffix, len(all_resources))
    poison_knn = None
    if use_cache and cache_file.exists():
        try:
            with open(cache_file, "rb") as f:
                cached = pickle.load(f)
            if cached.get("n_resources") == len(all_resources):
                poison_knn = cached["knn"]
                all_resources = cached["resources"]
        except Exception:
            poison_knn = None  # corrupt/stale cache -> just refit

    if poison_knn is None:
        texts = [r["url2text"][:1500] for r in all_resources]
        # kb._embed_many hardcodes batch_size=4; call the model directly with a
        # larger batch for CPU throughput (kb._embed_many's positional/duplicate
        # kwarg means it can't be overridden through that wrapper).
        if kb.embedding_model is None:
            kb._setup_embedding_model()
        embeddings = kb.embedding_model.embed_many(texts, batch_size=32)
        poison_knn = NearestNeighbors(n_neighbors=min(10, len(all_resources))).fit(embeddings)
        if use_cache:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "wb") as f:
                pickle.dump({"knn": poison_knn,
                             "resources": all_resources,
                             "n_resources": len(all_resources)}, f)

    kb.embedding_knns[cid] = poison_knn
    kb.cached_resources = all_resources
    kb.cached_resources_claim_id = cid
    kb.current_claim_id = cid
    kb._poison_knn = poison_knn  # stash for direct kneighbors
    return True


def retrieve_poisoned(kb, query: str, k: int) -> list[tuple]:
    """Top-k (url, text, is_fake) for `query` against the installed poisoned KB."""
    knn = kb._poison_knn
    qe = kb._embed(query).reshape(1, -1)
    kk = min(k, knn.n_samples_fit_)
    _, idx = knn.kneighbors(qe, kk)
    out = []
    for i in idx[0]:
        url, text, _ = kb.retrieve(int(i))
        out.append((url, text, "/created" in (url or "")))
    return out
