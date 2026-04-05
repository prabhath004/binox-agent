"""LLM wrapper and shared utilities."""
from __future__ import annotations
import os, json, logging
from typing import Any
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger("research_agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

_client: OpenAI | None = None
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def get_openai_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


def call_llm(
    system: str, user: str, *, model: str | None = None,
    temperature: float = 0.2, max_tokens: int = 1024, json_mode: bool = False,
) -> tuple[str, int, int]:
    """Returns (content, prompt_tokens, completion_tokens)."""
    kwargs: dict[str, Any] = {
        "model": model or MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    resp = get_openai_client().chat.completions.create(**kwargs)
    msg = resp.choices[0].message.content or ""
    return msg, resp.usage.prompt_tokens, resp.usage.completion_tokens


def parse_json_safe(text: str) -> dict | list | None:
    text = text.strip()
    if text.startswith("```"):
        lines = [l for l in text.splitlines() if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSON from LLM output")
        return None
