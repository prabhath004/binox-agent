"""Final report synthesis from compressed evidence."""
from __future__ import annotations
from app.budget import BudgetTracker
from app.memory import MemoryStore
from app.utils import call_llm, parse_json_safe, logger

SYNTH_SYSTEM = """You are a research analyst writing a structured report. Return JSON:
{
  "answer": "EXACTLY 3 paragraphs separated by \\n\\n — see structure below",
  "sections": [{"sub_question": "...", "finding": "1-2 sentences with company names + numbers", "confidence": "high|medium|low|none"}],
  "key_insights": ["insight1", "insight2", "insight3"],
  "limitations": ["limitation1", "limitation2"],
  "sources_used": ["file1.md", "file2.md"]
}

You MUST write EXACTLY 3 paragraphs in the answer field:

PARAGRAPH 1 — Answer the first part of the question.
List every relevant company with price and source. Be specific: "Windsurf $15/mo [09_windsurf.md], Cursor $20/mo [01_cursor.md]"

PARAGRAPH 2 — Answer the second part of the question.
For each company, state its strengths, weaknesses, or best use case from the evidence. Example: "Cursor excels at deep IDE integration but depends on VS Code updates [01_cursor.md]. Devin handles autonomous multi-step tasks but costs $500/mo and has reliability concerns [07_devin.md]."

PARAGRAPH 3 — Give a verdict.
Who should pick what? Make a clear recommendation backed by evidence. "For budget: X. For autonomy: Y. Best overall: Z because..."

RULES:
- ONLY use facts from evidence. Never invent.
- EVERY company mentioned needs price + source citation.
- NEVER write one paragraph. ALWAYS three.
- Confidence "none" for sub-questions with no evidence.
Return ONLY valid JSON."""


def synthesize(objective: str, sub_questions: list[str], memory: MemoryStore, budget: BudgetTracker) -> dict:
    evidence_text = memory.all_evidence_text() or memory.working_notes

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

    result["budget_report"] = budget.report()
    result["memory_state"] = memory.to_dict()
    return result
