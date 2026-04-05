"""Final report synthesis from compressed evidence."""
from __future__ import annotations
from app.budget import BudgetTracker
from app.memory import MemoryStore
from app.utils import call_llm, parse_json_safe, logger

SYNTH_SYSTEM = """You are a research synthesizer. Given objective, sub-questions, and evidence from a knowledge base, return JSON:
{
  "answer": "2-3 paragraph synthesis with inline [source.md] citations",
  "sections": [{"sub_question": "...", "finding": "1-2 sentences", "confidence": "high|medium|low|none"}],
  "key_insights": ["insight1", "insight2", "insight3"],
  "limitations": ["limitation1", "limitation2"],
  "sources_used": ["file1.md", "file2.md"]
}

RULES:
- ONLY use facts from provided evidence. Do NOT fill gaps with general knowledge.
- Name specific companies, products, prices. Cite sources inline.
- If no evidence for a sub-question, say "No evidence retrieved" with confidence "none".
- Compare directly when evidence supports it (e.g. "$10/mo vs $20/mo").
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
        prompt = prompt[: budget.config.max_context_tokens_per_step * 4]
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
