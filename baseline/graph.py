# graph.py
#
# LangGraph pipeline (linear):
#   START → build_prompt → call_llm → parse_label → store_result → END
#
# Each node is a plain function: receives full state, returns partial update dict.

import os
from pathlib import Path
from typing import Optional

from langfuse import get_client, propagate_attributes
from langfuse.langchain import CallbackHandler
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from label_parser import parse_label as _parse_label
from llm_client import call_glm
from result_store import append_result, make_record

_PROMPT_TEMPLATE = (
    Path(__file__).parent / "prompt_template.md"
).read_text(encoding="utf-8")

# Langfuse v3: reads LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL from env
_langfuse = get_client()


# ── State schema ──────────────────────────────────────────────────────────────

class ClaimState(TypedDict):
    # inputs
    claim_id:   int
    claim:      str
    gold_label: str
    # intermediate
    prompt:     str
    # LLM outputs
    raw_output:     str
    thinking_trace: str
    latency_ms:     float
    model_name:     str
    # parsed result
    predicted_label: Optional[str]
    parse_success:   bool
    # error capture
    error: Optional[str]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def build_prompt(state: ClaimState) -> dict:
    prompt = _PROMPT_TEMPLATE.replace("[CLAIM]", state["claim"])
    return {"prompt": prompt}


def call_llm(state: ClaimState) -> dict:
    try:
        resp = call_glm(state["prompt"])
        return {
            "raw_output":     resp.content,
            "thinking_trace": resp.thinking,
            "latency_ms":     resp.latency_ms,
            "model_name":     resp.model_name,
            "error":          None,
        }
    except Exception as exc:
        return {
            "raw_output":     "",
            "thinking_trace": "",
            "latency_ms":     0.0,
            "model_name":     os.environ.get("MODEL_NAME", "unknown"),
            "error":          f"LLM call failed: {exc}",
        }


def parse_label(state: ClaimState) -> dict:
    if state.get("error"):
        return {"predicted_label": None, "parse_success": False}

    label, success = _parse_label(state["raw_output"])

    if not success:
        print(
            f"[parse_label] WARN: could not extract label for claim_id={state['claim_id']}. "
            f"Snippet: {state['raw_output'][:120]!r}"
        )

    return {"predicted_label": label, "parse_success": success}


def store_result(state: ClaimState) -> dict:
    record = make_record(
        claim_id=state["claim_id"],
        claim=state["claim"],
        gold_label=state["gold_label"],
        predicted_label=state.get("predicted_label"),
        raw_model_output=state.get("raw_output", ""),
        thinking_trace=state.get("thinking_trace", ""),
        parse_success=state.get("parse_success", False),
        latency_ms=state.get("latency_ms", 0.0),
        model_name=state.get("model_name", ""),
    )
    append_result(record)

    status = "OK" if state.get("parse_success") else "PARSE_FAIL"
    print(
        f"[{state['claim_id']:>4}] {status} | "
        f"gold={state['gold_label']!r:30s} pred={state.get('predicted_label')!r} "
        f"({state.get('latency_ms', 0):.0f}ms)"
    )
    return {}


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(ClaimState)
    g.add_node("build_prompt", build_prompt)
    g.add_node("call_llm",     call_llm)
    g.add_node("parse_label",  parse_label)
    g.add_node("store_result", store_result)
    g.add_edge(START,          "build_prompt")
    g.add_edge("build_prompt", "call_llm")
    g.add_edge("call_llm",     "parse_label")
    g.add_edge("parse_label",  "store_result")
    g.add_edge("store_result", END)
    return g.compile()


graph = build_graph()


def run_single_claim(claim_id: int, claim: str, gold_label: str) -> ClaimState:
    langfuse_handler = CallbackHandler()

    initial_state: ClaimState = {
        "claim_id":        claim_id,
        "claim":           claim,
        "gold_label":      gold_label,
        "prompt":          "",
        "raw_output":      "",
        "thinking_trace":  "",
        "latency_ms":      0.0,
        "model_name":      "",
        "predicted_label": None,
        "parse_success":   False,
        "error":           None,
    }

    with propagate_attributes(
        trace_name="baseline-veracity-prediction",
        metadata={"claim_id": str(claim_id), "gold_label": gold_label},
    ):
        final_state = graph.invoke(
            initial_state,
            config={"callbacks": [langfuse_handler]},
        )

    return final_state
