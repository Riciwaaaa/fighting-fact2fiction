"""
Shared helpers for the symmetric evidence-fusion defense pipeline (run 05).

This module is deliberately *import-clean*: it imports only stdlib and the
`baseline/` primitives (llm_client, label_parser). It NEVER imports either copy
of the `infact`/`config` packages, so it is safe to import from a script running
in the DEFAME env, the Fact2Fiction env, or a plain interpreter alike.

The pipeline replaces the old asymmetric defense (infact_supplement.py +
subclaim_defense.py). Instead of gating the model-only reasoner against InFact and
re-judging with InFact's own Judge, it pools evidence from BOTH the poisoned InFact
fact-check and the model-only reasoner, probes each evidence item for corroboration
against the poisoned KB, comments on each item's confidence, and lets a single
fusion judge issue the final verdict.

Every stage reads/writes one JSON file per claim under the run directory and skips
claims whose output already exists, so every stage is independently resumable.
The single source of truth for which claims are in scope is `<run_dir>/claims.json`
(see make_claim_manifest.py) -- no script hardcodes a claim-id list.

Run under /home/ubuntu/.venv312/bin/python3.12 for the KB-touching stages; the
pure-LLM stages (model-only, confidence, judge) run under any interpreter with the
`openai` package.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
BASELINE_DIR = REPO_ROOT / "baseline"
DEFAME_DIR = REPO_ROOT / "DEFAME"
F2F_SRC = REPO_ROOT / "Fact2Fiction" / "src"
DEV_JSON = REPO_ROOT / "DEFAME" / "data" / "AVeriTeC" / "dev.json"
DEFAULT_RUN_DIR = EXPERIMENTS_DIR / "runs" / "05_mimo_100claim_fusion"

# Default OpenRouter model id used for every LLM role in the fusion pipeline
# (model-only reasoner, evidence wording, verification-query generation,
# confidence commentary, fusion judge). Overridable per script via --model.
DEFAULT_MODEL = "xiaomi/mimo-v2.5-pro"

# Import call_glm DIRECTLY from baseline (it pulls in only openai/os/time). Do NOT
# route through evidence_rag_probe: that module chdirs into DEFAME and imports the
# DEFAME `infact` copy at import time, which collides with the Fact2Fiction copy in
# any script that needs the poisoned KB.
sys.path.insert(0, str(BASELINE_DIR))
from llm_client import call_glm  # noqa: E402

REPAIR_SUFFIX = ("\n\nYour previous response could not be parsed as valid JSON. "
                 "Return ONLY the JSON object in a fenced ```json code block. No other text.")


def load_env_file(path: Path) -> None:
    """Minimal .env loader (python-dotenv is not installed in this venv)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def set_model(model: str) -> None:
    """Point call_glm at `model` and verify the API key is available."""
    load_env_file(BASELINE_DIR / ".env")
    os.environ["MODEL_NAME"] = model
    if "OPENROUTER_API_KEY" not in os.environ:
        sys.exit("OPENROUTER_API_KEY not set (baseline/.env)")


def extract_json(text: str) -> dict | None:
    """Best-effort extraction of a JSON object from model output."""
    if not text:
        return None
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = match.group(1) if match else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]
    if candidate is None:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _call_resilient(prompt: str, attempts: int = 4):
    """`call_glm` with backoff on transport failures.

    The provider intermittently answers with a non-JSON body (a gateway error page),
    which surfaces as an exception from the HTTP client rather than as an unparseable
    model answer -- so the JSON-repair retry below never sees it, and one bad response
    would otherwise kill a whole batch run.
    """
    delay = 2.0
    for attempt in range(attempts):
        try:
            return call_glm(prompt)
        except Exception as e:  # noqa: BLE001 -- any transport failure is retryable
            if attempt == attempts - 1:
                print(f"  LLM call failed after {attempts} attempts: {e}", file=sys.stderr,
                      flush=True)
                return None
            time.sleep(delay)
            delay *= 2
    return None


def call_json(prompt: str, validate) -> dict | None:
    """One LLM call plus a single JSON-repair retry, validated by `validate`."""
    resp = _call_resilient(prompt)
    data = extract_json(resp.content) if resp is not None else None
    if data is not None and validate(data):
        return data
    resp = _call_resilient(prompt + REPAIR_SUFFIX)
    data = extract_json(resp.content) if resp is not None else None
    if data is not None and validate(data):
        return data
    return None


def canon(label):
    """Normalize a verdict from any dialect to one canonical space."""
    if label is None:
        return None
    s = str(label).strip().lower()
    if not s:
        return None
    if s in ("supported", "support"):
        return "Supported"
    if s in ("refuted", "refute"):
        return "Refuted"
    if "conflict" in s or "cherry" in s:
        return "Conflicting"
    if "not enough" in s or s == "nei":
        return "NEI"
    return s


def load_manifest(run_dir: Path) -> dict:
    """Read <run_dir>/claims.json. Fails loudly if the manifest is missing."""
    path = Path(run_dir) / "claims.json"
    if not path.exists():
        sys.exit(f"No claim manifest at {path}. Run make_claim_manifest.py first.")
    with open(path) as f:
        return json.load(f)


def resolve_claim_ids(run_dir: Path, claims_arg: str | None) -> list[int]:
    """Claim ids for this run: an explicit --claims override, else the manifest."""
    if claims_arg:
        return [int(x) for x in claims_arg.split(",")]
    return list(load_manifest(run_dir)["claim_ids"])


def load_dev_claims() -> list[dict]:
    with open(DEV_JSON) as f:
        return json.load(f)
