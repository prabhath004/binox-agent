"""
Main entrypoint: FastAPI server + LangGraph pipeline.

Pipeline stages:
  1. plan      — decompose question into sub-questions
  2. retrieve  — fetch evidence from Chroma per sub-question
  3. compress  — shrink evidence to fit the token budget
  4. replan    — optionally add sub-questions if gaps found
  5. synthesize — produce the final structured report
"""

from __future__ import annotations

import time
import logging
from typing import TypedDict, List, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langgraph.graph import StateGraph, END

from app.budget import BudgetTracker, BudgetConfig
from app.memory import MemoryStore, EvidenceChunk, add_evidence, compress_if_needed
from app.planner import plan, maybe_replan
from app.retriever import retrieve_all
from app.synthesizer import synthesize
from app.utils import logger

# ────────────────────── FastAPI ──────────────────────

app = FastAPI(
    title="Deep Research Agent",
    description="Budget-aware research agent: planner → retriever → memory compression → synthesis",
    version="1.0.0",
)


class ResearchRequest(BaseModel):
    query: str
    max_cost_usd: float = 0.05
    max_chunks: int = 8
    max_context_tokens: int = 2000
    max_replans: int = 2


class ResearchResponse(BaseModel):
    answer: str
    sub_questions: List[str]
    sections: List[Dict[str, Any]]
    key_insights: List[str]
    limitations: List[str]
    sources_used: List[str]
    budget_report: Dict[str, Any]
    memory_state: Dict[str, Any]
    elapsed_seconds: float


# ────────────────────── LangGraph state ──────────────────────

class AgentState(TypedDict):
    query: str
    objective: str
    sub_questions: List[str]
    success_criteria: str
    evidence: List[Dict[str, Any]]
    memory: Dict[str, Any]
    budget_tracker: Any  # BudgetTracker (not serialisable, passed by ref)
    memory_store: Any    # MemoryStore
    result: Dict[str, Any]
    answered_questions: List[str]


# ────────────────────── Pipeline nodes ──────────────────────

def plan_node(state: AgentState) -> dict:
    """Decompose user query into sub-questions."""
    budget: BudgetTracker = state["budget_tracker"]
    research_plan = plan(state["query"], budget)

    return {
        "objective": research_plan.get("objective", state["query"]),
        "sub_questions": research_plan.get("sub_questions", [state["query"]]),
        "success_criteria": research_plan.get("success_criteria", ""),
    }


def retrieve_node(state: AgentState) -> dict:
    """Retrieve evidence for all pending sub-questions."""
    budget: BudgetTracker = state["budget_tracker"]
    store: MemoryStore = state["memory_store"]
    answered = state.get("answered_questions", [])
    pending = [q for q in state["sub_questions"] if q not in answered]

    chunks = retrieve_all(pending, budget, top_k=3)
    store = add_evidence(store, chunks, budget)

    return {
        "memory_store": store,
        "answered_questions": answered + pending,
    }


def compress_node(state: AgentState) -> dict:
    """Compress evidence if it exceeds the per-step token budget."""
    budget: BudgetTracker = state["budget_tracker"]
    store: MemoryStore = state["memory_store"]
    store = compress_if_needed(store, budget)
    return {"memory_store": store}


def replan_node(state: AgentState) -> dict:
    """Optionally add sub-questions if gaps exist."""
    budget: BudgetTracker = state["budget_tracker"]
    store: MemoryStore = state["memory_store"]

    new_qs = maybe_replan(
        state["objective"],
        state.get("answered_questions", []),
        store.all_evidence_text(),
        budget,
    )

    if new_qs:
        return {"sub_questions": state["sub_questions"] + new_qs}

    return {}


def should_retrieve_again(state: AgentState) -> str:
    """After replan, check if new sub-questions were added."""
    budget: BudgetTracker = state["budget_tracker"]
    answered = set(state.get("answered_questions", []))
    pending = [q for q in state["sub_questions"] if q not in answered]

    if pending and not budget.is_over_budget() and budget.remaining_chunks() > 0:
        return "retrieve"
    return "synthesize"


def synthesize_node(state: AgentState) -> dict:
    """Produce the final research report."""
    budget: BudgetTracker = state["budget_tracker"]
    store: MemoryStore = state["memory_store"]

    result = synthesize(
        state["objective"],
        state["sub_questions"],
        store,
        budget,
    )
    return {"result": result}


# ────────────────────── Build graph ──────────────────────

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("plan", plan_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("compress", compress_node)
    graph.add_node("replan", replan_node)
    graph.add_node("synthesize", synthesize_node)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "retrieve")
    graph.add_edge("retrieve", "compress")
    graph.add_edge("compress", "replan")
    graph.add_conditional_edges(
        "replan",
        should_retrieve_again,
        {"retrieve": "retrieve", "synthesize": "synthesize"},
    )
    graph.add_edge("synthesize", END)

    return graph


_compiled_graph = build_graph().compile()


# ────────────────────── Run pipeline ──────────────────────

def run_research(request: ResearchRequest) -> dict:
    """Execute the full research pipeline."""
    config = BudgetConfig(
        max_context_tokens_per_step=request.max_context_tokens,
        max_retrieved_chunks=request.max_chunks,
        max_cost_usd=request.max_cost_usd,
        max_replans=request.max_replans,
    )
    budget = BudgetTracker(config)
    memory = MemoryStore()

    initial_state: AgentState = {
        "query": request.query,
        "objective": "",
        "sub_questions": [],
        "success_criteria": "",
        "evidence": [],
        "memory": {},
        "budget_tracker": budget,
        "memory_store": memory,
        "result": {},
        "answered_questions": [],
    }

    start = time.time()
    final_state = _compiled_graph.invoke(initial_state)
    elapsed = time.time() - start

    result = final_state.get("result", {})
    result["sub_questions"] = final_state.get("sub_questions", [])
    result["elapsed_seconds"] = round(elapsed, 2)

    return result


# ────────────────────── API endpoints ──────────────────────

@app.post("/research", response_model=ResearchResponse)
async def research_endpoint(request: ResearchRequest):
    """Run a deep research query under budget constraints."""
    try:
        result = run_research(request)
        return ResearchResponse(
            answer=result.get("answer", ""),
            sub_questions=result.get("sub_questions", []),
            sections=result.get("sections", []),
            key_insights=result.get("key_insights", []),
            limitations=result.get("limitations", []),
            sources_used=result.get("sources_used", []),
            budget_report=result.get("budget_report", {}),
            memory_state=result.get("memory_state", {}),
            elapsed_seconds=result.get("elapsed_seconds", 0),
        )
    except Exception as e:
        logger.exception("Research pipeline failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok", "service": "deep-research-agent"}


# ────────────────────── CLI runner ──────────────────────

def cli_demo():
    """Run a demo question from the command line."""
    import json
    import sys

    query = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "Analyze top AI developer tooling startups, compare pricing, risks, and differentiation."
    )

    print(f"\n{'='*70}")
    print(f"DEEP RESEARCH AGENT — Budget-Constrained Pipeline")
    print(f"{'='*70}")
    print(f"Query: {query}\n")

    req = ResearchRequest(query=query)
    result = run_research(req)

    print(f"\n{'─'*70}")
    print("SUB-QUESTIONS:")
    for i, q in enumerate(result.get("sub_questions", []), 1):
        print(f"  {i}. {q}")

    print(f"\n{'─'*70}")
    print("ANSWER:")
    print(result.get("answer", "No answer generated"))

    print(f"\n{'─'*70}")
    print("KEY INSIGHTS:")
    for insight in result.get("key_insights", []):
        print(f"  • {insight}")

    print(f"\n{'─'*70}")
    print("LIMITATIONS:")
    for lim in result.get("limitations", []):
        print(f"  • {lim}")

    print(f"\n{'─'*70}")
    print("BUDGET REPORT:")
    print(json.dumps(result.get("budget_report", {}), indent=2))

    print(f"\n{'─'*70}")
    print("MEMORY STATE:")
    print(json.dumps(result.get("memory_state", {}), indent=2))

    print(f"\nCompleted in {result.get('elapsed_seconds', 0)}s")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    cli_demo()
