"""Three-tier memory system with LLM-powered compression."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any
from app.budget import BudgetTracker
from app.utils import call_llm, logger

COMPRESS_PROMPT = """You are a research-note compressor. Produce a bulleted summary.

CRITICAL: Never mix up companies. Each bullet must follow this format:
  - CompanyName: fact [source.md]

Rules:
1. KEEP every company name + its specific price (e.g. "Cody: $9/mo [04_cody.md]")
2. KEEP every risk/limitation attached to the CORRECT company
3. NEVER attribute one company's features to another company
4. REMOVE generic filler and marketing language
5. Group by: Pricing, Risks, Differentiation

Keep it under {target_tokens} tokens. Return ONLY the notes."""


@dataclass
class EvidenceChunk:
    sub_question: str
    text: str
    source: str
    relevance_score: float = 0.0


@dataclass
class MemoryStore:
    working_notes: str = ""
    evidence: List[EvidenceChunk] = field(default_factory=list)
    compressed_summaries: List[str] = field(default_factory=list)
    skipped_chunks: List[Dict[str, Any]] = field(default_factory=list)

    def all_evidence_text(self) -> str:
        parts = [f"[{c.source}] {c.text}" for c in self.evidence]
        parts.extend(self.compressed_summaries)
        return "\n\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "working_notes": self.working_notes,
            "evidence_chunks": len(self.evidence),
            "compressed_summaries": len(self.compressed_summaries),
            "skipped_chunks": len(self.skipped_chunks),
        }


def _evidence_key(chunk: EvidenceChunk) -> tuple[str, str]:
    return chunk.source, chunk.text[:200]


def add_evidence(store: MemoryStore, chunks: List[EvidenceChunk], budget: BudgetTracker) -> MemoryStore:
    existing = {_evidence_key(chunk) for chunk in store.evidence}
    deduped: List[EvidenceChunk] = []
    for chunk in chunks:
        key = _evidence_key(chunk)
        if key in existing:
            logger.info("Skipped duplicate chunk already in memory [%s]", chunk.source)
            continue
        existing.add(key)
        deduped.append(chunk)

    chunks = deduped
    remaining = budget.remaining_chunks()
    if len(chunks) > remaining:
        chunks = sorted(chunks, key=lambda c: c.relevance_score, reverse=True)
        for d in chunks[remaining:]:
            store.skipped_chunks.append({"sub_question": d.sub_question, "source": d.source, "reason": "chunk_budget"})
            logger.info("Dropped chunk [%s] — chunk budget", d.source)
        chunks = chunks[:remaining]

    store.evidence.extend(chunks)
    budget.record_retrieval(len(chunks))
    return store


def compress_if_needed(store: MemoryStore, budget: BudgetTracker) -> MemoryStore:
    combined = store.all_evidence_text()
    if not budget.needs_compression(combined):
        return store

    logger.info("Compression triggered — evidence is %d tokens (limit %d)",
                budget.count_tokens(combined), budget.config.max_context_tokens_per_step)

    target = max(128, budget.config.max_context_tokens_per_step // 2)
    system = COMPRESS_PROMPT.format(target_tokens=target)
    summary, pin, pout = call_llm(system, "Compress this evidence:\n\n" + combined, max_tokens=target)
    budget.record_llm_call(pin, pout)
    budget.record_compression()

    store.compressed_summaries = [summary]
    store.evidence = []
    store.working_notes = summary
    logger.info("Compressed to %d tokens", budget.count_tokens(summary))
    return store
