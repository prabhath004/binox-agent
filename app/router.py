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

# **Cursor** product name (disambiguation — read before “Unsure”)
- In this API the corpus covers the **Cursor AI code editor**. Treat **Cursor** as that **product by default** in short or ambiguous asks.
- **research**: the **editor** — e.g. only the word **cursor**; **what is cursor** / **what's cursor**; **tell me about Cursor**; **Cursor** with pricing, features, install, **vs** / **versus** / **compare** (even with words in between, e.g. “cursor coding agent vs Replit”); any **comparison** of **Cursor** to other **AI coding tools** or IDEs in the in-scope category (Replit, Copilot, Windsurf, VS Code, etc.).
- **general**: they **explicitly** mean a **mouse, text caret, or SQL/database cursor** (e.g. “mouse cursor”, “SQL cursor”, “cursor in MySQL”, “database cursor”, “fetch cursor”, “blinking cursor”).

# Use **general** when (including but not limited to)
- World knowledge: mythology, epics, religion, classical or modern literature, history, geography, culture, politics, sports, celebrities, medicine, law, business unrelated to AI dev tools above.
- Generic programming or CS education (what is recursion, what is a GUI, how does HTTP work) **unless** the user is clearly asking about **named products** in the in-scope list or **that product category as covered in the docs**.
- Homework, riddles, creative writing, translation, personal advice.
- Casually **naming** two dev tools (e.g. “I use Cursor and Replit”) **without** asking for differences, **vs**, which is better, or a direct **comparison** → **general**.
- **Unsure** whether the topic is in-corpus → **general** (avoid false retrieval). **Exception:** for **Cursor**-only ambiguity, follow the **Cursor** block above (product-default **research**; **general** only when SQL/UI cursor is explicit).

# Use **research** only when
The user is clearly asking about **tools/vendors/themes inside the in-scope description**: e.g. product comparisons, pricing, features, risks, market positioning of AI coding assistants **as covered by the ingested corpus**, including the **Cursor** editor per the **Cursor** block.

# Output format (mandatory)
Return **only** a UTF-8 JSON object, no markdown fences, no explanation. Exactly this shape:
{{"route":"research"}}
or
{{"route":"general"}}

The value must be lowercase ASCII exactly `research` or `general`."""


_ROUTE_IN_JSON = re.compile(r'"route"\s*:\s*"((?:research|general))"', re.IGNORECASE)

# UI / SQL “cursor” — do not send to product RAG
_CURSOR_NON_PRODUCT = re.compile(
    r"mouse\s+cursor|text\s+cursor|sql\s+cursor|database\s+cursor|"
    r"blinking\s+cursor|(?:^|\s)caret(?:\s|$)|fetch\s+cursor|server[-\s]side\s+cursor|"
    r"cursor\s+in\s+(?:mysql|sql|postgres|postgresql|oracle|mssql|sqlite)|"
    r"\b(?:mysql|postgres|postgresql|oracle|mssql|sqlite|pl/?sql|tsql)\b.{0,48}\bcursor\b|"
    r"\bcursor\b.{0,48}\b(?:mysql|postgres|postgresql|oracle|mssql|sqlite|pl/?sql|result\s+set)\b",
    re.IGNORECASE,
)

_LOOKUP_INTENT = re.compile(
    r"^(?:what\s+(?:'s|is)|tell me about|explain|describe|overview of)\b|"
    r"\b(?:pricing|price|features?|risks?|limitations?|differentiat(?:e|ion)|"
    r"compare|comparison|vs\.?|versus|better|best|cheapest|market|tool|editor|ide|agent)\b",
    re.IGNORECASE,
)

_COMPARISON_INTENT = re.compile(
    r"\b(?:compare|comparison|vs\.?|versus|compared\s+to|better|best|cheaper|cheapest)\b",
    re.IGNORECASE,
)

_IN_SCOPE_PRODUCT_PATTERNS = [
    re.compile(r"\b(?:github\s+copilot|copilot)\b", re.IGNORECASE),
    re.compile(r"\breplit\b", re.IGNORECASE),
    re.compile(r"\btabnine\b", re.IGNORECASE),
    re.compile(r"\bwindsurf\b", re.IGNORECASE),
    re.compile(r"\bdevin\b", re.IGNORECASE),
    re.compile(r"\bvercel\s+v0\b|(?<!\w)v0(?!\w)", re.IGNORECASE),
    re.compile(r"\bsourcegraph\s+cody\b", re.IGNORECASE),
    re.compile(r"\bbolt\.new\b", re.IGNORECASE),
]


def _heuristic_cursor_route(query: str) -> str | None:
    """Cursor editor vs mouse/SQL cursor. None → use LLM classifier."""
    if not re.search(r"\bcursor\b", query, re.IGNORECASE):
        return None
    if _CURSOR_NON_PRODUCT.search(query):
        return "general"
    t = query.strip()
    if re.fullmatch(r"cursor[?.!]?\s*", t, re.IGNORECASE):
        return "research"
    if re.match(
        r"^(what\s+('s|is)|who\s+(is|'re)|tell me about|explain|describe|overview of)\s+cursor\b",
        t,
        re.IGNORECASE,
    ):
        return "research"
    if re.search(
        r"\bcursor\b.{0,140}\b(?:vs\.?|versus|compared\s+to)\b|\b(?:vs\.?|versus|compared\s+to)\b.{0,140}\bcursor\b|"
        r"\bcursor\b\s*(?:vs\.?|versus|compared\s+to|or)\s+|\b(?:vs\.?|versus)\s+cursor\b|"
        r"\bcompare\b.{0,120}\bcursor\b|\bcursor\b.{0,120}\bcompare\b|"
        r"\bcursor\b.{0,40}\b(pricing|price|features?|install|download|editor|ide|product|app|ai|agent)\b|"
        r"\b(pricing|price|features?|install|download|editor|ide|agent)\b.{0,40}\bcursor\b",
        t,
        re.IGNORECASE,
    ):
        return "research"
    return None


def _heuristic_in_scope_product_route(query: str) -> str | None:
    """Catch direct product lookups/comparisons before the LLM classifier."""
    t = query.strip()
    matched = sum(1 for pattern in _IN_SCOPE_PRODUCT_PATTERNS if pattern.search(t))
    if matched == 0:
        return None
    if matched >= 2 and _COMPARISON_INTENT.search(t):
        return "research"
    if matched == 1 and _LOOKUP_INTENT.search(t):
        return "research"
    return None


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

    cursor_route = _heuristic_cursor_route(q)
    if cursor_route is not None:
        logger.info(
            "Router (cursor heuristic): %s → %s",
            q[:120] + ("…" if len(q) > 120 else ""),
            cursor_route,
        )
        return cursor_route

    product_route = _heuristic_in_scope_product_route(q)
    if product_route is not None:
        logger.info(
            "Router (product heuristic): %s → %s",
            q[:120] + ("…" if len(q) > 120 else ""),
            product_route,
        )
        return product_route

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
