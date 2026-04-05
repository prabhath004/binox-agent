"""
Planner: decomposes a user question into a structured research plan.

Output schema:
{
  "objective": "...",
  "sub_questions": ["q1", "q2", ...],
  "success_criteria": "..."
}
"""

from __future__ import annotations

from typing import List

from app.budget import BudgetTracker
from app.utils import call_llm, parse_json_safe, logger

PLANNER_SYSTEM = """You are a research planner.
Given a complex question, produce a JSON object with:
- "objective": a one-sentence restatement of what the user wants
- "sub_questions": a list of 3–6 focused sub-questions that, when answered, fully address the objective
- "success_criteria": what a good final answer must include

Rules:
- Each sub-question should be independently searchable
- Order them logically (definitions first, comparisons later)
- Keep it under 6 sub-questions to stay within budget
Return ONLY valid JSON."""

REPLAN_SYSTEM = """You are a research replanner.
Given the original objective, the sub-questions already answered,
and the evidence collected so far, decide if:
1. The current plan is sufficient → return {"replan": false}
2. New sub-questions are needed → return {"replan": true, "new_sub_questions": [...]}

Rules:
- Add at most 2 new sub-questions
- Only replan if critical gaps exist
Return ONLY valid JSON."""


def plan(query: str, budget: BudgetTracker) -> dict:
    """Decompose user query into a research plan."""
    raw, pin, pout = call_llm(
        PLANNER_SYSTEM,
        query,
        json_mode=True,
        max_tokens=512,
    )
    budget.record_llm_call(pin, pout)

    result = parse_json_safe(raw)
    if result is None:
        logger.error("Planner returned unparseable JSON, using fallback")
        result = {
            "objective": query,
            "sub_questions": [query],
            "success_criteria": "Answer the question accurately.",
        }

    logger.info(
        "Plan: %d sub-questions for '%s'",
        len(result.get("sub_questions", [])),
        result.get("objective", ""),
    )
    return result


def maybe_replan(
    objective: str,
    answered: List[str],
    evidence_summary: str,
    budget: BudgetTracker,
) -> List[str] | None:
    """
    Check whether the plan needs additional sub-questions.
    Returns new sub-questions or None.
    """
    if not budget.can_replan():
        logger.info("Replan skipped — replan budget exhausted")
        return None

    prompt = (
        f"Objective: {objective}\n\n"
        f"Already answered:\n" + "\n".join(f"- {q}" for q in answered) + "\n\n"
        f"Evidence so far:\n{evidence_summary}\n\n"
        "Should we add more sub-questions?"
    )

    raw, pin, pout = call_llm(
        REPLAN_SYSTEM,
        prompt,
        json_mode=True,
        max_tokens=256,
    )
    budget.record_llm_call(pin, pout)
    budget.record_replan()

    result = parse_json_safe(raw)
    if result and result.get("replan"):
        new_qs = result.get("new_sub_questions", [])
        logger.info("Replan added %d sub-questions", len(new_qs))
        return new_qs

    return None
