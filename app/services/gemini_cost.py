"""Gemini token usage and cost estimates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


CHARS_PER_TOKEN = 4

GEMINI_STANDARD_PRICES_PER_1M = {
    "gemini-flash-lite-latest": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash-lite-preview-09-2025": {"input": 0.10, "output": 0.40},
    "gemini-flash-latest": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
}

DEFAULT_MODEL = "gemini-2.5-flash-lite"


@dataclass(frozen=True)
class GeminiUsageEstimate:
    model: str | None
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    is_estimated: bool

    def as_debug_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "is_estimated": self.is_estimated,
        }


def estimate_tokens_from_chars(char_count: int) -> int:
    """Estimate token count from character count using a conservative text ratio."""
    if char_count <= 0:
        return 0
    return max(1, round(char_count / CHARS_PER_TOKEN))


def estimate_cost_usd(
    model: str | None,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Estimate Gemini standard-tier text cost in USD."""
    prices = GEMINI_STANDARD_PRICES_PER_1M.get(model or "", GEMINI_STANDARD_PRICES_PER_1M[DEFAULT_MODEL])
    cost = (
        (max(input_tokens, 0) / 1_000_000) * prices["input"]
        + (max(output_tokens, 0) / 1_000_000) * prices["output"]
    )
    return round(cost, 6)


def usage_from_metadata(
    model: str | None,
    usage_metadata: Any,
    prompt_chars: int,
    response_chars: int,
) -> GeminiUsageEstimate:
    """Build a cost estimate from Gemini metadata, falling back to chars if needed."""
    input_tokens = _metadata_int(usage_metadata, "prompt_token_count")
    output_tokens = _metadata_int(usage_metadata, "candidates_token_count")
    is_estimated = False

    if input_tokens is None:
        input_tokens = estimate_tokens_from_chars(prompt_chars)
        is_estimated = True
    if output_tokens is None:
        output_tokens = estimate_tokens_from_chars(response_chars)
        is_estimated = True

    return GeminiUsageEstimate(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=estimate_cost_usd(model, input_tokens, output_tokens),
        is_estimated=is_estimated,
    )


def _metadata_int(usage_metadata: Any, name: str) -> int | None:
    if usage_metadata is None:
        return None

    value = getattr(usage_metadata, name, None)
    if value is None and isinstance(usage_metadata, dict):
        value = usage_metadata.get(name)
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None
