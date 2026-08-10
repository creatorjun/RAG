# src/enterprise_rag/domain/context_budget.py
from __future__ import annotations

import math
from dataclasses import dataclass

from enterprise_rag.domain.errors import revision_error


@dataclass(frozen=True, slots=True)
class TokenBudget:
    maximum_context_tokens: int
    prompt_tokens: int
    max_output_tokens: int
    reserved_tokens: int
    input_budget_ratio: float

    def __post_init__(self) -> None:
        integer_values = (
            self.maximum_context_tokens,
            self.prompt_tokens,
            self.max_output_tokens,
            self.reserved_tokens,
        )
        if any(value < 0 for value in integer_values):
            raise ValueError("token budget values must be non-negative")
        if self.maximum_context_tokens == 0:
            raise ValueError("maximum context must be positive")
        if not math.isfinite(self.input_budget_ratio) or not 0 < self.input_budget_ratio <= 1:
            raise ValueError("input budget ratio must be within zero and one")
        if self.content_capacity_tokens <= 0:
            raise ValueError("token budget has no content capacity")

    @property
    def content_capacity_tokens(self) -> int:
        hard_capacity = (
            self.maximum_context_tokens
            - self.prompt_tokens
            - self.max_output_tokens
            - self.reserved_tokens
        )
        ratio_capacity = (
            math.floor(self.maximum_context_tokens * self.input_budget_ratio) - self.prompt_tokens
        )
        return min(hard_capacity, ratio_capacity)

    def total_tokens(self, content_tokens: int) -> int:
        return self.prompt_tokens + content_tokens + self.max_output_tokens + self.reserved_tokens

    def ensure_fits(self, content_tokens: int) -> None:
        if content_tokens < 0 or content_tokens > self.content_capacity_tokens:
            raise revision_error(
                "TOKEN_BUDGET_EXCEEDED",
                {
                    "content_tokens": content_tokens,
                    "content_capacity_tokens": self.content_capacity_tokens,
                },
            )
