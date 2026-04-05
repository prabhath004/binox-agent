"""
Synthesizer: produces the final structured research report.

Uses only the compressed evidence memory — never the raw full corpus —
so the synthesis step always fits within the per-step token budget.
"""

from __future__ import annotations

from app.budget import BudgetTracker
from app.memory import MemoryStore
from app.utils import call_llm, parse_json_safe, logger

SYNTH_SYSTEM = """You are a research synthesizer.
Given an objective, sub-questions, and compressed evidence notes,
produce a JSON report with:

{
  "answer": "A structured, multi-paragraph answer addressing the objective",
  "sections": [
    {"sub_question": "...", "finding": "...", "confidence": "high|medium|low"}
  ],
  "key_insights": ["...", "..."],
  "limitations": ["...", "..."],
  "sources_used": ["...", "..."]
}

Rules:
- Cite sources inline when possible
- Flag low-confidence sections honestly
- Note what was skipped due to budget constraints
Return ONLY valid JSON."""


def synthesize(
    objective: str,
    sub_questions: list[str],
    memory: MemoryStore,
    budget: BudgetTracker,
) -> dict:
    """Produce the final research report from compressed evidence."""
    evidence_text = memory.all_evidence_text() or memory.working_notes

    skipped_info = ""
    if memory.skipped_chunks:
        sources = [s["source"] for s in memory.skipped_chunks]
        skipped_info = f"\n\nSkipped sources (budget): {', '.join(sources)}"

    prompt = (
        f"## Objective\n{objective}\n\n"
        f"## Sub-questions\n"
        + "\n".join(f"- {q}" for q in sub_questions)
        + f"\n\n## Evidence\n{evidence_text}"
        + skipped_info
    )

    if budget.needs_compression(prompt):
        prompt = prompt[: budget.config.max_context_tokens_per_step * 4]
        logger.warning("Synthesis prompt truncated to fit budget")

    raw, pin, pout = call_llm(
        SYNTH_SYSTEM,
        prompt,
        json_mode=True,
        max_tokens=1024,
    )
    budget.record_llm_call(pin, pout)

    result = parse_json_safe(raw)
    if result is None:
        result = {
            "answer": raw,
            "sections": [],
            "key_insights": [],
            "limitations": ["JSON parsing failed — raw output returned"],
            "sources_used": [],
        }

    result["budget_report"] = budget.report()
    result["memory_state"] = memory.to_dict()
    return result
