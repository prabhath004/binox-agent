"""FastAPI server + LangGraph pipeline orchestration."""
from __future__ import annotations
import time, json, sys, logging
from typing import TypedDict, List, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langgraph.graph import StateGraph, END

from app.budget import BudgetTracker, BudgetConfig
from app.memory import MemoryStore, add_evidence, compress_if_needed
from app.planner import plan, maybe_replan
from app.retriever import retrieve_all
from app.synthesizer import synthesize
from app.utils import logger

app = FastAPI(title="Deep Research Agent", version="1.0.0")


class ResearchRequest(BaseModel):
    query: str
    max_cost_usd: float = 0.05
    max_chunks: int = 20
    max_context_tokens: int = 800
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


class AgentState(TypedDict):
    query: str
    objective: str
    sub_questions: List[str]
    success_criteria: str
    evidence: List[Dict[str, Any]]
    memory: Dict[str, Any]
    budget_tracker: Any
    memory_store: Any
    result: Dict[str, Any]
    answered_questions: List[str]


# --- Pipeline nodes ---

def plan_node(state: AgentState) -> dict:
    budget: BudgetTracker = state["budget_tracker"]
    research_plan = plan(state["query"], budget)
    return {
        "objective": research_plan.get("objective", state["query"]),
        "sub_questions": research_plan.get("sub_questions", [state["query"]]),
        "success_criteria": research_plan.get("success_criteria", ""),
    }


def retrieve_node(state: AgentState) -> dict:
    budget, store = state["budget_tracker"], state["memory_store"]
    answered = state.get("answered_questions", [])
    pending = [q for q in state["sub_questions"] if q not in answered]
    store = add_evidence(store, retrieve_all(pending, budget, top_k=5), budget)
    return {"memory_store": store, "answered_questions": answered + pending}


def compress_node(state: AgentState) -> dict:
    return {"memory_store": compress_if_needed(state["memory_store"], state["budget_tracker"])}


def replan_node(state: AgentState) -> dict:
    new_qs = maybe_replan(
        state["objective"], state.get("answered_questions", []),
        state["memory_store"].all_evidence_text(), state["budget_tracker"],
    )
    return {"sub_questions": state["sub_questions"] + new_qs} if new_qs else {}


def should_retrieve_again(state: AgentState) -> str:
    budget = state["budget_tracker"]
    answered = set(state.get("answered_questions", []))
    pending = [q for q in state["sub_questions"] if q not in answered]
    if pending and not budget.is_over_budget() and budget.remaining_chunks() > 0:
        return "retrieve"
    return "synthesize"


def synthesize_node(state: AgentState) -> dict:
    return {"result": synthesize(state["objective"], state["sub_questions"], state["memory_store"], state["budget_tracker"])}


# --- Graph ---

def build_graph() -> StateGraph:
    g = StateGraph(AgentState)
    for name, fn in [("plan", plan_node), ("retrieve", retrieve_node), ("compress", compress_node), ("replan", replan_node), ("synthesize", synthesize_node)]:
        g.add_node(name, fn)
    g.set_entry_point("plan")
    g.add_edge("plan", "retrieve")
    g.add_edge("retrieve", "compress")
    g.add_edge("compress", "replan")
    g.add_conditional_edges("replan", should_retrieve_again, {"retrieve": "retrieve", "synthesize": "synthesize"})
    g.add_edge("synthesize", END)
    return g


_graph = build_graph().compile()


def run_research(request: ResearchRequest) -> dict:
    config = BudgetConfig(
        max_context_tokens_per_step=request.max_context_tokens,
        max_retrieved_chunks=request.max_chunks,
        max_cost_usd=request.max_cost_usd,
        max_replans=request.max_replans,
    )
    initial: AgentState = {
        "query": request.query, "objective": "", "sub_questions": [],
        "success_criteria": "", "evidence": [], "memory": {},
        "budget_tracker": BudgetTracker(config), "memory_store": MemoryStore(),
        "result": {}, "answered_questions": [],
    }
    start = time.time()
    final = _graph.invoke(initial)
    result = final.get("result", {})
    result["sub_questions"] = final.get("sub_questions", [])
    result["elapsed_seconds"] = round(time.time() - start, 2)
    return result


# --- API ---

@app.post("/research", response_model=ResearchResponse)
async def research_endpoint(request: ResearchRequest):
    try:
        r = run_research(request)
        return ResearchResponse(
            answer=r.get("answer", ""), sub_questions=r.get("sub_questions", []),
            sections=r.get("sections", []), key_insights=r.get("key_insights", []),
            limitations=r.get("limitations", []), sources_used=r.get("sources_used", []),
            budget_report=r.get("budget_report", {}), memory_state=r.get("memory_state", {}),
            elapsed_seconds=r.get("elapsed_seconds", 0),
        )
    except Exception as e:
        logger.exception("Pipeline failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok"}


# --- CLI ---

def cli_demo():
    query = sys.argv[1] if len(sys.argv) > 1 else "Analyze top AI developer tooling startups, compare pricing, risks, and differentiation."

    print(f"\n{'='*70}\nDEEP RESEARCH AGENT\n{'='*70}\nQuery: {query}\n")
    result = run_research(ResearchRequest(query=query))

    print(f"{'─'*70}\nSUB-QUESTIONS:")
    for i, q in enumerate(result.get("sub_questions", []), 1):
        print(f"  {i}. {q}")

    print(f"\n{'─'*70}\nANSWER:\n{result.get('answer', 'No answer generated')}")

    print(f"\n{'─'*70}\nKEY INSIGHTS:")
    for x in result.get("key_insights", []):
        print(f"  • {x}")

    print(f"\n{'─'*70}\nLIMITATIONS:")
    for x in result.get("limitations", []):
        print(f"  • {x}")

    print(f"\n{'─'*70}\nBUDGET REPORT:\n{json.dumps(result.get('budget_report', {}), indent=2)}")
    print(f"\n{'─'*70}\nMEMORY STATE:\n{json.dumps(result.get('memory_state', {}), indent=2)}")
    print(f"\nCompleted in {result.get('elapsed_seconds', 0)}s\n{'='*70}\n")


if __name__ == "__main__":
    cli_demo()
