"""Query router — classifies queries and routes to RAG pipeline or direct GPT."""
from __future__ import annotations
from app.utils import call_llm, logger

ROUTER_PROMPT = """Classify this query. Respond with ONLY one word: research or general

"research" = about AI developer tools, coding assistants, IDEs, AI editors, or these products: Cursor, Copilot, GitHub, Replit, Cody, Sourcegraph, Tabnine, Windsurf, Codeium, Devin, Continue, v0, Vercel, Bolt.new, StackBlitz

"general" = anything else

Examples: "Compare Cursor vs Copilot" → research | "Risks of Devin" → research | "Capital of France" → general"""


def classify_query(query: str) -> str:
    raw, _, _ = call_llm(ROUTER_PROMPT, query, max_tokens=5, temperature=0)
    route = raw.strip().lower()
    if "research" in route:
        return "research"
    return "general"


def direct_gpt_answer(query: str) -> str:
    system = ("You are a helpful assistant. Answer directly and concisely. "
              "This question is outside the AI developer tooling knowledge base.")
    raw, _, _ = call_llm(system, query, max_tokens=1024, temperature=0.3)
    return raw
