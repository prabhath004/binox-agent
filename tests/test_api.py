from fastapi.testclient import TestClient

import app.main as main
import app.router as router


client = TestClient(main.app)


def test_research_request_validation_rejects_blank_query():
    response = client.post("/research", json={"query": "   "})
    assert response.status_code == 422


def test_research_request_validation_rejects_invalid_budget():
    response = client.post("/research", json={"query": "Compare Cursor vs Replit", "max_chunks": 0})
    assert response.status_code == 422


def test_route_falls_back_to_direct_gpt_when_research_has_no_evidence(monkeypatch):
    monkeypatch.setattr(router, "classify_query", lambda query: "research")
    monkeypatch.setattr(
        main,
        "run_research",
        lambda request: {
            "answer": "No relevant evidence was retrieved from the research corpus for this query.",
            "sub_questions": ["What is Cursor?"],
            "sections": [],
            "key_insights": [],
            "limitations": ["No relevant corpus evidence was retrieved for this query."],
            "sources_used": [],
            "budget_report": {"note": "research attempted"},
            "memory_state": {
                "working_notes": "",
                "evidence_chunks": 0,
                "compressed_summaries": 0,
                "skipped_chunks": 0,
            },
            "elapsed_seconds": 0.01,
        },
    )
    monkeypatch.setattr(router, "direct_gpt_answer", lambda query: "fallback answer")

    response = client.post("/route", json={"query": "what is cursor"})
    body = response.json()

    assert response.status_code == 200
    assert body["routed_to"] == "direct_gpt_fallback"
    assert body["router_label"] == "research"
    assert body["answer"] == "fallback answer"
    assert "No relevant corpus evidence was retrieved" in body["limitations"][0]

