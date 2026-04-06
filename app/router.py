"""Query router — classifies queries and routes to RAG pipeline or direct GPT."""
from __future__ import annotations
import json
import os
import re

from app.utils import call_llm

# What the vector store / RAG actually covers — override with RAG_CORPUS_SCOPE in .env
_DEFAULT_CORPUS_SCOPE = (
    "Commercial AI-powered coding assistants and IDE-style tools "
    "(e.g. products developers pay for or install for AI code completion, chat, or agents in the editor), "
    "including their features, pricing, comparisons, positioning, and the market for those tools."
)

_CURSOR_PRODUCT_DISAMBIGUATION = (
    "Disambiguation: the software product named Cursor (AI code editor) matches this corpus; "
    "SQL or mouse/database cursors do not."
)


def get_corpus_scope() -> str:
    return (os.getenv("RAG_CORPUS_SCOPE") or _DEFAULT_CORPUS_SCOPE).strip() or _DEFAULT_CORPUS_SCOPE


def build_router_system_prompt() -> str:
    scope = get_corpus_scope()
    return f"""You classify a user question for routing.

The specialized knowledge base (RAG) contains ONLY material that fits this scope:
{scope}

{_CURSOR_PRODUCT_DISAMBIGUATION}

Reply with a single JSON object and no other text. Shape: {{"route":"<value>"}} where <value> is exactly research or general.

Choose research only when the user is primarily seeking information that would reasonably be found in that knowledge base (they are asking about tools, vendors, or themes inside that scope).

Choose general when their question is mainly about anything outside that scope, or when a reasonable answer does not require that specialized corpus — including world facts, unrelated domains, generic programming or CS concepts, homework, entertainment, religion, history, etc.

If you are unsure, choose general."""


def classify_query(query: str) -> str:
    raw, _, _ = call_llm(
        build_router_system_prompt(),
        query,
        max_tokens=64,
        temperature=0,
        json_mode=True,
    )
    try:
        route = json.loads(raw.strip()).get("route", "general")
        return "research" if str(route).lower().strip() == "research" else "general"
    except (json.JSONDecodeError, TypeError, AttributeError):
        first = re.sub(r"[^a-z]+", " ", raw.strip().lower()).split()
        return "research" if (first[0] if first else "") == "research" else "general"


def direct_gpt_answer(query: str) -> str:
    system = ("You are a helpful assistant. Answer directly and concisely. "
              "This question is outside the scope described by the specialized knowledge base.")
    raw, _, _ = call_llm(system, query, max_tokens=1024, temperature=0.3)
    return raw
