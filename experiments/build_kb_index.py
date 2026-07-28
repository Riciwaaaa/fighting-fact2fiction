"""
Phase 0.5: extend the clean KB embedding index to cover the new claims.

The downloaded dev knowledge base ships resource files for all 500 claims but a
prebuilt kNN index (embedding_knns.pckl) for only claims 0-99. Clean InFact (Phase 1)
and the attack's clean-retrieval baseline (Phase 2) both look up
embedding_knns[claim_id], so the new claims (dev 100+) need their per-claim kNN built
and inserted first. (Phase 4's poisoned KB refits its own KNN and does NOT need this.)

This reproduces KnowledgeBase._build_knns_cpu's per-claim logic exactly -- truncate
each resource's text to 1500 chars, embed, fit NearestNeighbors(10), or store None if
the claim has no natural-language resources -- but only for the manifest's new claim
ids, merging into the existing embedding_knns.pckl. Idempotent: claim ids already
present in the index are skipped. A backup of the original index is written once.

Must run under /home/ubuntu/.venv312/bin/python3.12, in the DEFAME env.
"""

import argparse
import gc
import json
import pickle
import shutil
import sys
from pathlib import Path

try:
    import torch  # noqa: F401
    import langdetect
    from sklearn.neighbors import NearestNeighbors
except ImportError:
    sys.exit("Run with /home/ubuntu/.venv312/bin/python3.12 (needs torch/sklearn/langdetect).")

import os

from fusion_common import DEFAME_DIR, DEFAULT_RUN_DIR, load_manifest

# Dev resource files are huge (up to ~190M chars / claim). KnowledgeBase._get_resources
# joins and holds the FULL text of every resource at once, which -- on top of the ~1 GB
# base index already in RAM and the embedding model -- OOM-kills this 7 GB box. We only
# ever embed the first 1500 chars, so stream the JSONL and truncate per line, never
# holding a claim's full text. The filter (drop empty; langdetect-gate texts < 512 chars)
# and the resulting order are replicated EXACTLY from _get_resources so that KNN index i
# still maps to the same resource that KnowledgeBase.retrieve(i) returns at query time.
EMBED_TRUNC = 1500


def embed_chunked(model, texts: list[str], batch_size: int):
    """Embed in bounded slices, freeing each slice's activations before the next.

    sentence-transformers pads every batch to its longest member, so peak memory scales
    with batch_size x longest text. Measured on claim 108 (1310 texts): batch_size=32
    peaked at 3.5 GB and got OOM-killed on this 7 GB box. Encoding a slice at a time and
    dropping the intermediate keeps the peak flat regardless of how many resources the
    claim has.
    """
    import numpy as np

    out = []
    slice_size = max(batch_size, 64)  # encode this many per call, in batch_size batches
    for i in range(0, len(texts), slice_size):
        vecs = model.embed_many(texts[i:i + slice_size], batch_size=batch_size)
        out.append(np.asarray(vecs))
        del vecs
        gc.collect()
    return np.concatenate(out, axis=0) if out else np.empty((0, model.dimension))


def stream_truncated_texts(resource_path: Path) -> list[str]:
    texts = []
    with open(resource_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            u2t = r.get("url2text")
            text = "\n".join(u2t) if isinstance(u2t, list) else (u2t or "")
            if not text:
                continue
            if len(text) < 512:
                try:
                    lang = langdetect.detect(text)
                except langdetect.LangDetectException:
                    lang = None
                if lang is None:
                    continue
            texts.append(text[:EMBED_TRUNC])
    return texts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=str, default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--claims", type=str, default=None,
                        help="Comma-separated override; default = new_claim_ids from the manifest")
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--batch-size", type=int, default=4,
                        help="Embedding batch size. Peak RAM scales with this x the longest "
                             "text in the batch; 32 OOM-kills this 7 GB box on big claims.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if args.claims:
        target_ids = [int(x) for x in args.claims.split(",")]
    else:
        target_ids = list(load_manifest(run_dir)["new_claim_ids"])

    os.chdir(DEFAME_DIR)
    sys.path.insert(0, str(DEFAME_DIR))
    from infact.tools.search.knowledge_base import KnowledgeBase

    kb = KnowledgeBase(variant="dev", device=args.device)
    index_path = kb.embedding_knns_path
    have = set(kb.embedding_knns.keys())
    todo = [cid for cid in target_ids if cid not in have or kb.embedding_knns.get(cid) is None]
    print(f"KB index currently covers {len(have)} claims. "
          f"{len(target_ids)} requested, {len(todo)} to build.")
    if not todo:
        print("Nothing to build.")
        return

    # One-time backup of the original 0-99 index.
    backup = index_path.with_suffix(".pckl.bak")
    if not backup.exists():
        shutil.copy2(index_path, backup)
        print(f"Backed up original index -> {backup}")

    kb._setup_embedding_model()
    resources_dir = kb.resources_dir
    n_built, n_empty = 0, 0
    for cid in todo:
        texts = stream_truncated_texts(resources_dir / f"{cid}.json")
        n_texts = len(texts)
        if texts:
            embeddings = embed_chunked(kb.embedding_model, texts, args.batch_size)
            kb.embedding_knns[cid] = NearestNeighbors(n_neighbors=min(10, n_texts)).fit(embeddings)
            del embeddings
            n_built += 1
        else:
            kb.embedding_knns[cid] = None
            n_empty += 1
        del texts
        gc.collect()  # release the claim's texts/activations before the next (huge) claim
        # Persist after every claim so a kill doesn't lose progress. Re-read the on-disk
        # index and merge before writing: atomicity alone only stops torn reads, not lost
        # updates -- two builders each holding their own dict would clobber each other's
        # claims (this actually happened when a duplicate chain ran concurrently). Merging
        # keeps whatever anyone else has added; ours wins only for the claim we just built.
        # The temp file is per-process so two writers cannot share a partial file.
        merged = kb.embedding_knns
        if index_path.exists():
            try:
                with open(index_path, "rb") as f:
                    on_disk = pickle.load(f)
                on_disk.update(kb.embedding_knns)
                merged = on_disk
                kb.embedding_knns = merged
            except Exception:
                pass  # unreadable mid-write -> just persist what we have
        tmp_path = index_path.with_suffix(f".pckl.tmp{os.getpid()}")
        with open(tmp_path, "wb") as f:
            pickle.dump(merged, f)
        os.replace(tmp_path, index_path)
        print(f"[{cid}] {'built' if n_texts else 'EMPTY (index=None)'} "
              f"({n_texts} resources)", flush=True)

    print(f"Done. {n_built} indices built, {n_empty} empty. "
          f"Index now covers {len(kb.embedding_knns)} claims -> {index_path}")


if __name__ == "__main__":
    main()
