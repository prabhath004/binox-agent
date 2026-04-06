"""Query router — classifies queries and routes to RAG pipeline or direct GPT."""
from __future__ import annotations
import re

from app.utils import call_llm

ROUTER_PROMPT = """You route requests for a knowledge base about AI coding assistants (products like Cursor, Copilot, Windsurf, Tabnine, Cody, Codeium, Devin, Replit, v0, etc.).

Return exactly one lowercase English word and nothing else: research or general

research — The user wants information that belongs in that corpus: a named AI dev tool, features, pricing, comparisons, benchmarks, or the AI coding-tool market.

general — Everything else: movies, sports, trivia, school homework, plain CS definitions (GUI, API, HTTP, SQL, recursion), database/mouse cursors, politics, health, etc.

Rules: "Cursor" meaning the Cursor IDE app → research. SQL/database/mouse "cursor" → general. If you are not sure → general.

Examples: Compare Cursor vs Copilot → research | what is Cursor → research | what is GUI → general | what is bahubali → general"""


def classify_query(query: str) -> str:
    raw, _, _ = call_llm(ROUTER_PROMPT, query, max_tokens=5, temperature=0)
    first = re.sub(r"[^a-z]+", " ", raw.strip().lower()).split()
    return "research" if (first[0] if first else "") == "research" else "general"


def direct_gpt_answer(query: str) -> str:
    system = ("You are a helpful assistant. Answer directly and concisely. "
              "This question is outside the AI developer tooling knowledge base.")
    raw, _, _ = call_llm(system, query, max_tokens=1024, temperature=0.3)
    return raw
