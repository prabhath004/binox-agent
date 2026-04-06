"""Final report synthesis from compressed evidence."""
from __future__ import annotations
from app.budget import BudgetTracker
from app.memory import MemoryStore
from app.utils import call_llm, parse_json_safe, logger

SYNTH_SYSTEM = """You are a research analyst. Given an objective and evidence, return JSON with this EXACT structure:
{
  "answer_part1": "First part of the question answered with specific facts and [source.md] citations.",
  "answer_part2": "Second part answered with trade-offs, comparisons, or limitations from evidence.",
  "answer_part3": "Direct conclusion or recommendation grounded in the evidence.",
  "sections": [{"sub_question": "...", "finding": "specific finding with names+numbers", "confidence": "high|medium|low|none"}],
  "key_insights": ["insight1", "insight2", "insight3"],
  "limitations": ["what evidence was missing"],
  "sources_used": ["file1.md", "file2.md"]
}

RULES:
- Each answer_part MUST be 3-5 sentences. Never just one sentence.
- Use ONLY facts from evidence. If the evidence is missing, say so explicitly.
- Cite claims inline as [source.md].
- Do not invent facts, prices, product names, dates, or source citations.
- Be direct and specific. No filler phrases.
Return ONLY valid JSON."""


def _no_evidence_result(objective: str, sub_questions: list[str], memory: MemoryStore, budget: BudgetTracker) -> dict:
    scoped_sub_questions = sub_questions or [objective]
    return {
        "answer": (
            "No relevant evidence was retrieved from the research corpus for this query, "
            "so the agent cannot produce a grounded research answer."
        ),
        "sections": [
            {
                "sub_question": question,
                "finding": "No relevant corpus evidence found.",
                "confidence": "none",
            }
            for question in scoped_sub_questions
        ],
        "key_insights": [],
        "limitations": [
            "No relevant corpus evidence was retrieved for this query.",
            "Final answer was withheld to avoid unsupported claims.",
        ],
        "sources_used": [],
        "budget_report": budget.report(),
        "memory_state": memory.to_dict(),
    }


def synthesize(objective: str, sub_questions: list[str], memory: MemoryStore, budget: BudgetTracker) -> dict:
    evidence_text = memory.all_evidence_text() or memory.working_notes
    if not evidence_text.strip():
        logger.warning("Synthesis skipped — no evidence available for objective '%s'", objective)
        return _no_evidence_result(objective, sub_questions, memory, budget)

    skipped_info = ""
    if memory.skipped_chunks:
        sources = [s["source"] for s in memory.skipped_chunks]
        skipped_info = f"\n\nSkipped sources (budget): {', '.join(sources)}"

    prompt = (f"## Objective\n{objective}\n\n## Sub-questions\n"
              + "\n".join(f"- {q}" for q in sub_questions)
              + f"\n\n## Evidence\n{evidence_text}" + skipped_info)

    if budget.needs_compression(prompt):
        prompt = prompt[: budget.config.max_context_tokens_per_step * 6]
        logger.warning("Synthesis prompt truncated to fit budget")

    raw, pin, pout = call_llm(SYNTH_SYSTEM, prompt, json_mode=True, max_tokens=2048)
    budget.record_llm_call(pin, pout)

    result = parse_json_safe(raw)
    if result is None:
        result = {"answer": raw, "sections": [], "key_insights": [],
                  "limitations": ["JSON parsing failed"], "sources_used": []}
    else:
        p1 = result.pop("answer_part1", "")
        p2 = result.pop("answer_part2", "")
        p3 = result.pop("answer_part3", "")
        result["answer"] = f"{p1}\n\n{p2}\n\n{p3}".strip()

    result["budget_report"] = budget.report()
    result["memory_state"] = memory.to_dict()
    return result
