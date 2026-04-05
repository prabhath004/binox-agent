"""Query decomposition and replanning."""
from __future__ import annotations
from typing import List
from app.budget import BudgetTracker
from app.utils import call_llm, parse_json_safe, logger

PLANNER_SYSTEM = """You are a research planner. Given a complex question, return JSON:
{"objective": "one-sentence restatement", "sub_questions": ["q1","q2",...], "success_criteria": "..."}

Rules:
- 3-6 sub-questions, each independently searchable against a document corpus
- Use concrete terms: "pricing", "risks", "product features", "differentiation", "market overview"
- Do NOT ask about subjective things like "customer reviews" or "satisfaction"
- Order logically (definitions first, comparisons later)
Return ONLY valid JSON."""

REPLAN_SYSTEM = """You are a research replanner. Given objective, answered questions, and evidence, decide:
1. Plan sufficient → {"replan": false}
2. Gaps exist → {"replan": true, "new_sub_questions": [...]}

Rules: max 2 new questions, only for critical factual gaps, must be corpus-searchable.
Return ONLY valid JSON."""


def plan(query: str, budget: BudgetTracker) -> dict:
    raw, pin, pout = call_llm(PLANNER_SYSTEM, query, json_mode=True, max_tokens=512)
    budget.record_llm_call(pin, pout)

    result = parse_json_safe(raw)
    if result is None:
        result = {"objective": query, "sub_questions": [query], "success_criteria": "Answer accurately."}

    logger.info("Plan: %d sub-questions for '%s'", len(result.get("sub_questions", [])), result.get("objective", ""))
    return result


def maybe_replan(objective: str, answered: List[str], evidence_summary: str, budget: BudgetTracker) -> List[str] | None:
    if not budget.can_replan():
        logger.info("Replan skipped — budget exhausted")
        return None

    prompt = (f"Objective: {objective}\n\nAlready answered:\n"
              + "\n".join(f"- {q}" for q in answered)
              + f"\n\nEvidence so far:\n{evidence_summary}\n\nShould we add more sub-questions?")

    raw, pin, pout = call_llm(REPLAN_SYSTEM, prompt, json_mode=True, max_tokens=256)
    budget.record_llm_call(pin, pout)
    budget.record_replan()

    result = parse_json_safe(raw)
    if result and result.get("replan"):
        new_qs = result.get("new_sub_questions", [])
        logger.info("Replan added %d sub-questions", len(new_qs))
        return new_qs
    return None
