"""FastAPI server + LangGraph pipeline orchestration."""
from __future__ import annotations
import json
import os
import sys
import time
from typing import TypedDict, List, Dict, Any

from fastapi.concurrency import run_in_threadpool
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from langgraph.graph import StateGraph, END

from app.budget import BudgetTracker, BudgetConfig
from app.memory import MemoryStore, add_evidence, compress_if_needed
from app.planner import plan, maybe_replan
from app.retriever import get_corpus_count, retrieve_all
from app.synthesizer import synthesize
from app.utils import logger

app = FastAPI(title="Deep Research Agent", version="1.0.0")


class ResearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    max_cost_usd: float = Field(default=0.05, gt=0, le=5)
    max_chunks: int = Field(default=20, ge=1, le=50)
    max_context_tokens: int = Field(default=800, ge=200, le=8000)
    max_replans: int = Field(default=2, ge=0, le=5)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        query = str(value).strip()
        if not query:
            raise ValueError("query must not be empty")
        return query


class ClassifyRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        query = str(value).strip()
        if not query:
            raise ValueError("query must not be empty")
        return query


class ResearchResponse(BaseModel):
    answer: str
    sub_questions: List[str]
    initial_sub_question_count: int | None = None
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
    initial_sub_question_count: int
    success_criteria: str
    evidence: List[Dict[str, Any]]
    memory: Dict[str, Any]
    budget_tracker: Any
    memory_store: Any
    result: Dict[str, Any]
    answered_questions: List[str]


# --- Hard budget cutoff ---

class BudgetExceeded(Exception):
    pass


def _check_hard_limit(budget: BudgetTracker):
    if budget.is_over_budget():
        budget.state.events.append("HARD_CUTOFF: budget exceeded, skipping to synthesis")
        logger.warning("HARD CUTOFF — cost $%.4f >= limit $%.2f", budget.state.estimated_cost, budget.config.max_cost_usd)
        raise BudgetExceeded()


# --- Pipeline nodes ---

def plan_node(state: AgentState) -> dict:
    budget: BudgetTracker = state["budget_tracker"]
    research_plan = plan(state["query"], budget)
    qs = research_plan.get("sub_questions", [state["query"]])
    objective = research_plan.get("objective", state["query"])
    success_criteria = research_plan.get("success_criteria", "")
    budget.remember_plan(
        objective=objective,
        sub_questions=qs,
        success_criteria=success_criteria,
        initial_sub_question_count=len(qs),
    )
    _check_hard_limit(budget)
    return {
        "objective": objective,
        "sub_questions": qs,
        "initial_sub_question_count": len(qs),
        "success_criteria": success_criteria,
    }


def retrieve_node(state: AgentState) -> dict:
    budget, store = state["budget_tracker"], state["memory_store"]
    _check_hard_limit(budget)
    answered = state.get("answered_questions", [])
    pending = [q for q in state["sub_questions"] if q not in answered]
    store = add_evidence(store, retrieve_all(pending, budget, top_k=5), budget)
    return {"memory_store": store, "answered_questions": answered + pending}


def compress_node(state: AgentState) -> dict:
    budget = state["budget_tracker"]
    _check_hard_limit(budget)
    return {"memory_store": compress_if_needed(state["memory_store"], budget)}


def replan_node(state: AgentState) -> dict:
    budget = state["budget_tracker"]
    _check_hard_limit(budget)
    new_qs = maybe_replan(
        state["objective"], state.get("answered_questions", []),
        state["memory_store"].all_evidence_text(), budget,
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


def _has_corpus_evidence(result: dict) -> bool:
    memory_state = result.get("memory_state", {})
    return bool(
        memory_state.get("evidence_chunks", 0)
        or memory_state.get("compressed_summaries", 0)
        or str(memory_state.get("working_notes", "")).strip()
    )


def _direct_response(
    answer: str,
    *,
    routed_to: str,
    limitation_notes: list[str],
    elapsed_seconds: float,
    budget_report: dict | None = None,
    memory_state: dict | None = None,
    sub_questions: list[str] | None = None,
    router_label: str | None = None,
) -> dict:
    payload = {
        "answer": answer,
        "routed_to": routed_to,
        "sub_questions": sub_questions or [],
        "sections": [],
        "key_insights": [],
        "limitations": limitation_notes,
        "sources_used": [],
        "budget_report": budget_report or {"note": "No research pipeline used — direct GPT response"},
        "memory_state": memory_state or {},
        "elapsed_seconds": elapsed_seconds,
    }
    if router_label is not None:
        payload["router_label"] = router_label
    return payload


def run_research(request: ResearchRequest) -> dict:
    config = BudgetConfig(
        max_context_tokens_per_step=request.max_context_tokens,
        max_retrieved_chunks=request.max_chunks,
        max_cost_usd=request.max_cost_usd,
        max_replans=request.max_replans,
    )
    budget = BudgetTracker(config)
    memory = MemoryStore()
    initial: AgentState = {
        "query": request.query, "objective": "", "sub_questions": [],
        "initial_sub_question_count": 0,
        "success_criteria": "", "evidence": [], "memory": {},
        "budget_tracker": budget, "memory_store": memory,
        "result": {}, "answered_questions": [],
    }
    start = time.time()
    last_state: AgentState = initial
    try:
        for state in _graph.stream(initial, stream_mode="values"):
            last_state = state
        final = last_state
        result = final.get("result", {})
        result["sub_questions"] = final.get("sub_questions", [])
        result["initial_sub_question_count"] = final.get("initial_sub_question_count", 0)
    except BudgetExceeded:
        logger.warning("Budget exceeded — forcing early synthesis with available evidence")
        snapshot = budget.plan_snapshot()
        memory_store = last_state.get("memory_store", memory)
        objective = last_state.get("objective") or snapshot["objective"] or initial["query"]
        sub_questions = last_state.get("sub_questions") or snapshot["sub_questions"] or [initial["query"]]
        result = synthesize(
            objective,
            sub_questions,
            memory_store,
            budget,
        )
        result["sub_questions"] = sub_questions
        result["initial_sub_question_count"] = (
            last_state.get("initial_sub_question_count")
            or snapshot["initial_sub_question_count"]
            or len(sub_questions)
        )
        result.setdefault("limitations", []).append("Research cut short — budget hard limit exceeded")
    result["elapsed_seconds"] = round(time.time() - start, 2)
    return result


# --- API ---

@app.post("/research", response_model=ResearchResponse)
async def research_endpoint(request: ResearchRequest):
    try:
        r = await run_in_threadpool(run_research, request)
        return ResearchResponse(
            answer=r.get("answer", ""), sub_questions=r.get("sub_questions", []),
            initial_sub_question_count=r.get("initial_sub_question_count"),
            sections=r.get("sections", []), key_insights=r.get("key_insights", []),
            limitations=r.get("limitations", []), sources_used=r.get("sources_used", []),
            budget_report=r.get("budget_report", {}), memory_state=r.get("memory_state", {}),
            elapsed_seconds=r.get("elapsed_seconds", 0),
        )
    except Exception as e:
        logger.exception("Pipeline failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/classify")
async def classify_endpoint(body: ClassifyRequest):
    """Route label only (research | general). Single source of truth for n8n + tools."""
    from app.router import classify_query

    route = await run_in_threadpool(classify_query, body.query)
    q = body.query
    return {"route": route, "query_echo": q}


@app.post("/route")
async def route_endpoint(request: ResearchRequest):
    """Query router: classifies query and routes to RAG pipeline or direct GPT."""
    from app.router import classify_query, direct_gpt_answer
    import time

    start = time.time()
    route = await run_in_threadpool(classify_query, request.query)
    logger.info("Query routed to: %s", route)

    if route == "research":
        try:
            r = await run_in_threadpool(run_research, request)
            if not _has_corpus_evidence(r):
                answer = await run_in_threadpool(direct_gpt_answer, request.query)
                return _direct_response(
                    answer,
                    routed_to="direct_gpt_fallback",
                    router_label=route,
                    sub_questions=r.get("sub_questions", []),
                    limitation_notes=[
                        "No relevant corpus evidence was retrieved for this query.",
                        "Answered from general knowledge fallback — not from research corpus.",
                    ],
                    budget_report=r.get("budget_report", {}),
                    memory_state=r.get("memory_state", {}),
                    elapsed_seconds=round(time.time() - start, 2),
                )
            r["routed_to"] = "research_pipeline"
            r["router_label"] = route
            return r
        except Exception as e:
            logger.exception("Pipeline failed")
            raise HTTPException(status_code=500, detail=str(e))
    else:
        answer = await run_in_threadpool(direct_gpt_answer, request.query)
        return _direct_response(
            answer,
            routed_to="direct_gpt",
            router_label=route,
            limitation_notes=["Answered from general knowledge — not from research corpus"],
            elapsed_seconds=round(time.time() - start, 2),
        )


@app.get("/health")
async def health():
    corpus_chunks = await run_in_threadpool(get_corpus_count)
    openai_configured = bool(os.getenv("OPENAI_API_KEY"))
    status = "ok" if corpus_chunks > 0 and openai_configured else "degraded"
    return {
        "status": status,
        "openai_configured": openai_configured,
        "corpus_chunks": corpus_chunks,
    }


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
