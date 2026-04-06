"""Query router — classifies queries and routes to RAG pipeline or direct GPT."""
from __future__ import annotations
import re

from app.utils import call_llm, logger

ROUTER_PROMPT = """You are a strict router for an AI developer-tools knowledge base.
Respond with EXACTLY one lowercase word: research or general. No punctuation.

research = query is specifically about AI coding assistants, IDE AI tools, or products like Cursor, Copilot, Windsurf, Tabnine, Cody, Codeium, Devin, v0, Replit, and similar — including their pricing, comparisons, or market analysis.

general = everything else (movies, sports, trivia, unrelated coding homework, etc.).
If unsure, answer general.

Examples: "Compare Cursor vs Copilot pricing" → research | "what is bahubali 2" → general"""

_TOOLING = re.compile(
    r"\b(cursor|copilot|github\s*copilot|windsurf|tabnine|cody|codeium|sourcegraph|continue\.dev|"
    r"devin|aider|cline|vscode|vs\s*code|jetbrains|intellij|neovim|\bide\b|ai\s*coding|coding\s*assistant|"
    r"code\s*completion|pair\s*programm|developer\s*tools?|dev\s*tools?|llm\s+for\s*code|replit|"
    r"bolt\.new|\bv0\b|vercel\s+v0|stackblitz|gitlab|\bgithub\b)\b",
    re.I,
)


def classify_query(query: str) -> str:
    raw, _, _ = call_llm(ROUTER_PROMPT, query, max_tokens=5, temperature=0)
    first = re.sub(r"[^a-z]+", " ", raw.strip().lower()).split()
    first_word = first[0] if first else ""
    llm_research = first_word == "research"
    if llm_research and _TOOLING.search(query):
        return "research"
    return "general"


def direct_gpt_answer(query: str) -> str:
    system = ("You are a helpful assistant. Answer directly and concisely. "
              "This question is outside the AI developer tooling knowledge base.")
    raw, _, _ = call_llm(system, query, max_tokens=1024, temperature=0.3)
    return raw
