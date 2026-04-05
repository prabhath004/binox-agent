"""
Memory system for the research agent.

Three tiers:
  1. Working memory  — current sub-question context (small, fits one step)
  2. Evidence memory  — compressed notes from retrieval (survives across steps)
  3. Long-term memory — full chunks stored in the vector DB (not loaded by default)

Compression is triggered whenever evidence exceeds the per-step token budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any

from app.budget import BudgetTracker
from app.utils import call_llm, logger

COMPRESS_SYSTEM = """You are a research-note compressor.
Given a set of evidence chunks, produce a concise bulleted summary that
preserves every factual claim and source reference.
Remove filler, redundancy, and boilerplate.  Keep it under {target_tokens} tokens.
Return ONLY the compressed notes — no preamble."""


@dataclass
class EvidenceChunk:
    sub_question: str
    text: str
    source: str
    relevance_score: float = 0.0


@dataclass
class MemoryStore:
    """State object carried through the LangGraph pipeline."""

    working_notes: str = ""
    evidence: List[EvidenceChunk] = field(default_factory=list)
    compressed_summaries: List[str] = field(default_factory=list)
    skipped_chunks: List[Dict[str, Any]] = field(default_factory=list)

    def all_evidence_text(self) -> str:
        parts = []
        for chunk in self.evidence:
            parts.append(f"[{chunk.source}] {chunk.text}")
        for summary in self.compressed_summaries:
            parts.append(summary)
        return "\n\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "working_notes": self.working_notes,
            "evidence_chunks": len(self.evidence),
            "compressed_summaries": len(self.compressed_summaries),
            "skipped_chunks": len(self.skipped_chunks),
        }


def add_evidence(
    store: MemoryStore,
    chunks: List[EvidenceChunk],
    budget: BudgetTracker,
) -> MemoryStore:
    """
    Add retrieved chunks to evidence memory.
    Drops low-relevance chunks if we're near the chunk budget.
    """
    remaining = budget.remaining_chunks()
    if len(chunks) > remaining:
        chunks = sorted(chunks, key=lambda c: c.relevance_score, reverse=True)
        kept = chunks[:remaining]
        dropped = chunks[remaining:]
        for d in dropped:
            store.skipped_chunks.append(
                {"sub_question": d.sub_question, "source": d.source, "reason": "chunk_budget"}
            )
            logger.info("Dropped chunk [%s] — chunk budget", d.source)
        chunks = kept

    store.evidence.extend(chunks)
    budget.record_retrieval(len(chunks))
    return store


def compress_if_needed(
    store: MemoryStore,
    budget: BudgetTracker,
) -> MemoryStore:
    """
    If combined evidence exceeds the per-step token window,
    summarize it into a shorter note block via the LLM.
    """
    combined = store.all_evidence_text()
    if not budget.needs_compression(combined):
        return store

    logger.info(
        "Compression triggered — evidence is %d tokens (limit %d)",
        budget.count_tokens(combined),
        budget.config.max_context_tokens_per_step,
    )

    target = budget.config.max_context_tokens_per_step // 2
    prompt = (
        "Compress the following research evidence into concise notes.\n\n"
        + combined
    )
    system = COMPRESS_SYSTEM.format(target_tokens=target)

    summary, pin, pout = call_llm(system, prompt, max_tokens=target)
    budget.record_llm_call(pin, pout)
    budget.record_compression()

    store.compressed_summaries = [summary]
    store.evidence = []
    store.working_notes = summary
    logger.info(
        "Compressed to %d tokens", budget.count_tokens(summary)
    )
    return store
