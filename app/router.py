"""Query router — classifies queries and routes to RAG pipeline or direct GPT."""
from __future__ import annotations
import json
import os
import re

from app.utils import call_llm, logger, parse_json_safe

# Natural-language description of ingested docs — set RAG_CORPUS_SCOPE in .env to match data/ reality.
_DEFAULT_CORPUS_SCOPE = (
    "Markdown notes profiling commercial AI-powered developer tools: specific products (editors, extensions, "
    "services) used for AI-assisted coding—features, pricing, positioning, risks, comparisons, and the market "
    "for those tools. The store is not a general encyclopedia, textbook, or literary corpus."
)

def get_corpus_scope() -> str:
    raw = (os.getenv("RAG_CORPUS_SCOPE") or "").strip()
    return raw if raw else _DEFAULT_CORPUS_SCOPE


def build_router_system_prompt() -> str:
    scope = get_corpus_scope()
    return f"""# Role
You are a strict routing classifier for a production API. Your only job is to output valid JSON that sends each user question down the correct backend path.

# What the "research" path actually does
The **research** path runs an expensive pipeline: it retrieves text chunks from a **vector database**, then a research agent plans sub-questions and synthesizes an answer **grounded in those chunks**. It must only run when the user's **main information need** is something those stored documents are meant to answer.

The **general** path answers with a normal LLM **without** retrieving from that vector store. Use it whenever the question does not depend on those documents.

# What the vector store is for (in-scope)
{scope}

# Routing test (apply mentally before answering)
1. What is the user mainly trying to learn?
2. Would a **correct, complete** answer require **specific facts** that live **only** in the product/market documents described above (not Wikipedia-style world knowledge)?
3. If **no** or **maybe** → **general**. If **yes, clearly** → **research**.

# Use **general** when (including but not limited to)
- World knowledge: mythology, epics, religion, classical or modern literature, history, geography, culture, politics, sports, celebrities, medicine, law, business unrelated to AI dev tools above.
- Generic programming or CS education (what is recursion, what is a GUI, how does HTTP work) **unless** the user is clearly asking about **named products** in the in-scope list or **that product category as covered in the docs**.
- Homework, riddles, creative writing, translation, personal advice.
- **Unsure** → **general** (prefer avoiding false retrieval).

# Use **research** only when
The user is clearly asking about **tools/vendors/themes inside the in-scope description**: e.g. product comparisons, pricing, features, risks, market positioning of AI coding assistants **as covered by the ingested corpus**.

# Product name disambiguation
- **Cursor** = the **AI code editor product** → in scope for research **when** the question is about that software.
- **Cursor** = SQL / mouse / database cursor → **general** (not the product).

# Output format (mandatory)
Return **only** a UTF-8 JSON object, no markdown fences, no explanation. Exactly this shape:
{{"route":"research"}}
or
{{"route":"general"}}

The value must be lowercase ASCII exactly `research` or `general`."""


_ROUTE_IN_JSON = re.compile(r'"route"\s*:\s*"((?:research|general))"', re.IGNORECASE)


def _parse_route_json(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    data = parse_json_safe(text)
    if isinstance(data, dict):
        r = data.get("route")
        if r is not None:
            s = str(r).lower().strip()
            if s in ("research", "general"):
                return s
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            s = str(data.get("route", "")).lower().strip()
            if s in ("research", "general"):
                return s
    except json.JSONDecodeError:
        pass
    m = _ROUTE_IN_JSON.search(text)
    if m:
        return m.group(1).lower()
    return None


def classify_query(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return "general"

    model = (os.getenv("ROUTER_MODEL") or "").strip() or None
    user_msg = (
        "Classify the following user message for backend routing.\n\n"
        "User message:\n---\n"
        f"{q}\n"
        "---\n\n"
        'Remember: output one JSON object only, with key "route" and value exactly '
        '"research" or "general" (lowercase).'
    )
    raw, _, _ = call_llm(
        build_router_system_prompt(),
        user_msg,
        model=model,
        max_tokens=96,
        temperature=0,
        json_mode=True,
    )

    parsed = _parse_route_json(raw)
    if parsed:
        route = parsed
    else:
        # Last resort: first alphabetic token (legacy models / truncated JSON)
        letters = re.sub(r"[^a-z]+", " ", raw.lower()).split()
        route = "research" if letters and letters[0] == "research" else "general"
        logger.warning("Router JSON parse failed; fallback token. Raw snippet: %r", raw[:200])

    logger.info("Router: %s → %s", q[:120] + ("…" if len(q) > 120 else ""), route)
    return route


def direct_gpt_answer(query: str) -> str:
    system = (
        "You are a helpful assistant. Answer directly and concisely, using your general knowledge. "
        "The user’s question was not routed to the specialized product-doc search pipeline."
    )
    raw, _, _ = call_llm(system, query.strip(), max_tokens=1024, temperature=0.3)
    return raw
