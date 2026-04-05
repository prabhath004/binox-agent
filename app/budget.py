"""
Budget tracker for the research agent.

Enforces hard limits on token usage, cost, retrieval chunks,
and replan attempts to keep each research run bounded.
"""

from __future__ import annotations

import tiktoken
from dataclasses import dataclass, field
from typing import List


# ---------- pricing (per 1K tokens, OpenAI gpt-4o-mini) ----------
INPUT_COST_PER_1K = 0.00015
OUTPUT_COST_PER_1K = 0.0006


@dataclass
class BudgetConfig:
    max_context_tokens_per_step: int = 2_000
    max_retrieved_chunks: int = 8
    max_cost_usd: float = 0.05
    max_replans: int = 2


@dataclass
class BudgetState:
    input_tokens: int = 0
    output_tokens: int = 0
    retrieved_chunks: int = 0
    replans_used: int = 0
    compression_events: int = 0
    events: List[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def estimated_cost(self) -> float:
        return (
            (self.input_tokens / 1_000) * INPUT_COST_PER_1K
            + (self.output_tokens / 1_000) * OUTPUT_COST_PER_1K
        )

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost, 6),
            "retrieved_chunks": self.retrieved_chunks,
            "replans_used": self.replans_used,
            "compression_events": self.compression_events,
            "events": self.events,
        }


class BudgetTracker:
    """Central budget enforcer — every LLM call and retrieval goes through here."""

    def __init__(self, config: BudgetConfig | None = None):
        self.config = config or BudgetConfig()
        self.state = BudgetState()
        self._enc = tiktoken.encoding_for_model("gpt-4o-mini")

    def count_tokens(self, text: str) -> int:
        return len(self._enc.encode(text))

    def record_llm_call(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.state.input_tokens += prompt_tokens
        self.state.output_tokens += completion_tokens
        self.state.events.append(
            f"llm_call: +{prompt_tokens} in / +{completion_tokens} out"
        )

    def record_retrieval(self, num_chunks: int) -> None:
        self.state.retrieved_chunks += num_chunks
        self.state.events.append(f"retrieval: +{num_chunks} chunks")

    def record_compression(self) -> None:
        self.state.compression_events += 1
        self.state.events.append("compression_event")

    def record_replan(self) -> None:
        self.state.replans_used += 1
        self.state.events.append("replan")

    # ---------- constraint checks ----------

    def can_retrieve(self, requested: int = 1) -> bool:
        return (
            self.state.retrieved_chunks + requested
            <= self.config.max_retrieved_chunks
        )

    def remaining_chunks(self) -> int:
        return max(
            0, self.config.max_retrieved_chunks - self.state.retrieved_chunks
        )

    def can_replan(self) -> bool:
        return self.state.replans_used < self.config.max_replans

    def is_over_budget(self) -> bool:
        return self.state.estimated_cost >= self.config.max_cost_usd

    def text_fits_step(self, text: str) -> bool:
        return self.count_tokens(text) <= self.config.max_context_tokens_per_step

    def needs_compression(self, text: str) -> bool:
        return self.count_tokens(text) > self.config.max_context_tokens_per_step

    def report(self) -> dict:
        return {
            **self.state.to_dict(),
            "limits": {
                "max_context_tokens_per_step": self.config.max_context_tokens_per_step,
                "max_retrieved_chunks": self.config.max_retrieved_chunks,
                "max_cost_usd": self.config.max_cost_usd,
                "max_replans": self.config.max_replans,
            },
            "budget_remaining_usd": round(
                self.config.max_cost_usd - self.state.estimated_cost, 6
            ),
            "chunks_remaining": self.remaining_chunks(),
        }
