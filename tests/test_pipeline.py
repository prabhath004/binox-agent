import app.main as main
import app.synthesizer as synthesizer
from app.budget import BudgetConfig, BudgetTracker
from app.memory import EvidenceChunk, MemoryStore, add_evidence


def test_synthesize_without_evidence_skips_llm(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("call_llm should not run when there is no evidence")

    monkeypatch.setattr(synthesizer, "call_llm", fail_if_called)

    result = synthesizer.synthesize(
        "Compare Cursor vs Replit",
        ["What is Cursor?"],
        MemoryStore(),
        BudgetTracker(),
    )

    assert "No relevant evidence was retrieved" in result["answer"]
    assert result["sections"][0]["confidence"] == "none"
    assert result["sources_used"] == []


def test_add_evidence_deduplicates_chunks_already_in_memory():
    store = MemoryStore(
        evidence=[
            EvidenceChunk(sub_question="q1", text="same chunk", source="01_cursor.md", relevance_score=0.9),
        ]
    )
    budget = BudgetTracker(BudgetConfig(max_retrieved_chunks=10))

    updated = add_evidence(
        store,
        [
            EvidenceChunk(sub_question="q2", text="same chunk", source="01_cursor.md", relevance_score=0.8),
            EvidenceChunk(sub_question="q2", text="new chunk", source="02_replit.md", relevance_score=0.85),
        ],
        budget,
    )

    assert len(updated.evidence) == 2
    assert updated.evidence[1].source == "02_replit.md"
    assert budget.state.retrieved_chunks == 1


def test_run_research_preserves_planned_sub_questions_on_budget_cutoff(monkeypatch):
    class FakeGraph:
        def stream(self, initial, stream_mode="values"):
            initial["budget_tracker"].remember_plan(
                objective="Planned objective",
                sub_questions=["q1", "q2"],
                success_criteria="Answer both",
                initial_sub_question_count=2,
            )
            if False:
                yield initial
            raise main.BudgetExceeded()

    monkeypatch.setattr(main, "_graph", FakeGraph())
    monkeypatch.setattr(
        main,
        "synthesize",
        lambda objective, sub_questions, memory, budget: {
            "answer": "fallback",
            "sections": [],
            "key_insights": [],
            "limitations": [],
            "sources_used": [],
            "budget_report": budget.report(),
            "memory_state": memory.to_dict(),
        },
    )

    result = main.run_research(main.ResearchRequest(query="original query"))

    assert result["sub_questions"] == ["q1", "q2"]
    assert result["initial_sub_question_count"] == 2
    assert "Research cut short" in result["limitations"][-1]

