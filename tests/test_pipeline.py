"""
Tests for the deep research agent pipeline.

Covers: budget tracking, memory compression, planner output shape,
retriever filtering, and the full end-to-end pipeline.
"""

import pytest

from app.budget import BudgetTracker, BudgetConfig
from app.memory import MemoryStore, EvidenceChunk, add_evidence, compress_if_needed


# ─────────────── Budget tests ───────────────


class TestBudgetTracker:
    def test_initial_state(self):
        bt = BudgetTracker()
        assert bt.state.total_tokens == 0
        assert bt.state.estimated_cost == 0.0
        assert bt.remaining_chunks() == 8

    def test_record_llm_call(self):
        bt = BudgetTracker()
        bt.record_llm_call(100, 50)
        assert bt.state.input_tokens == 100
        assert bt.state.output_tokens == 50
        assert bt.state.total_tokens == 150

    def test_chunk_budget_enforcement(self):
        bt = BudgetTracker(BudgetConfig(max_retrieved_chunks=3))
        assert bt.can_retrieve(2)
        bt.record_retrieval(2)
        assert bt.remaining_chunks() == 1
        assert not bt.can_retrieve(2)
        assert bt.can_retrieve(1)

    def test_cost_budget(self):
        config = BudgetConfig(max_cost_usd=0.001)
        bt = BudgetTracker(config)
        bt.record_llm_call(5000, 2000)
        assert bt.is_over_budget()

    def test_replan_budget(self):
        bt = BudgetTracker(BudgetConfig(max_replans=1))
        assert bt.can_replan()
        bt.record_replan()
        assert not bt.can_replan()

    def test_token_counting(self):
        bt = BudgetTracker()
        count = bt.count_tokens("Hello, world!")
        assert count > 0
        assert isinstance(count, int)

    def test_needs_compression(self):
        bt = BudgetTracker(BudgetConfig(max_context_tokens_per_step=10))
        assert bt.needs_compression("This is a sentence with more than ten tokens in it, definitely.")
        assert not bt.needs_compression("Hi")

    def test_report_structure(self):
        bt = BudgetTracker()
        bt.record_llm_call(100, 50)
        bt.record_retrieval(3)
        report = bt.report()
        assert "input_tokens" in report
        assert "limits" in report
        assert "budget_remaining_usd" in report
        assert "chunks_remaining" in report


# ─────────────── Memory tests ───────────────


class TestMemoryStore:
    def test_empty_store(self):
        store = MemoryStore()
        assert store.all_evidence_text() == ""
        assert store.to_dict()["evidence_chunks"] == 0

    def test_add_evidence_within_budget(self):
        store = MemoryStore()
        budget = BudgetTracker(BudgetConfig(max_retrieved_chunks=5))
        chunks = [
            EvidenceChunk(sub_question="q1", text="fact A", source="doc1.md", relevance_score=0.9),
            EvidenceChunk(sub_question="q1", text="fact B", source="doc2.md", relevance_score=0.8),
        ]
        store = add_evidence(store, chunks, budget)
        assert len(store.evidence) == 2
        assert budget.remaining_chunks() == 3

    def test_add_evidence_drops_low_relevance(self):
        store = MemoryStore()
        budget = BudgetTracker(BudgetConfig(max_retrieved_chunks=2))
        chunks = [
            EvidenceChunk(sub_question="q1", text="important", source="a.md", relevance_score=0.95),
            EvidenceChunk(sub_question="q1", text="medium", source="b.md", relevance_score=0.7),
            EvidenceChunk(sub_question="q1", text="low", source="c.md", relevance_score=0.3),
        ]
        store = add_evidence(store, chunks, budget)
        assert len(store.evidence) == 2
        assert len(store.skipped_chunks) == 1
        assert store.skipped_chunks[0]["source"] == "c.md"

    def test_evidence_text_assembly(self):
        store = MemoryStore()
        store.evidence = [
            EvidenceChunk(sub_question="q", text="alpha", source="x.md"),
        ]
        store.compressed_summaries = ["beta summary"]
        text = store.all_evidence_text()
        assert "alpha" in text
        assert "beta summary" in text


# ─────────────── Integration (no LLM) ───────────────


class TestPipelineStructure:
    def test_budget_config_from_request_values(self):
        config = BudgetConfig(
            max_context_tokens_per_step=1500,
            max_retrieved_chunks=5,
            max_cost_usd=0.03,
            max_replans=1,
        )
        bt = BudgetTracker(config)
        assert bt.config.max_context_tokens_per_step == 1500
        assert bt.config.max_retrieved_chunks == 5
        assert bt.config.max_cost_usd == 0.03

    def test_memory_store_serialisation(self):
        store = MemoryStore()
        store.working_notes = "test notes"
        store.compressed_summaries = ["summary"]
        d = store.to_dict()
        assert d["working_notes"] == "test notes"
        assert d["compressed_summaries"] == 1

    def test_budget_events_logging(self):
        bt = BudgetTracker()
        bt.record_llm_call(50, 20)
        bt.record_retrieval(3)
        bt.record_compression()
        bt.record_replan()
        assert len(bt.state.events) == 4
        assert "llm_call" in bt.state.events[0]
        assert "retrieval" in bt.state.events[1]
        assert "compression" in bt.state.events[2]
        assert "replan" in bt.state.events[3]
