from __future__ import annotations

from types import SimpleNamespace

from app.services.gemini_cost import estimate_cost_usd, estimate_tokens_from_chars, usage_from_metadata


def test_estimate_cost_usd_uses_flash_lite_prices():
    assert estimate_cost_usd("gemini-2.5-flash-lite", 1_000_000, 1_000_000) == 0.5


def test_estimate_cost_usd_uses_flash_prices():
    assert estimate_cost_usd("gemini-2.5-flash", 1_000_000, 1_000_000) == 2.8


def test_usage_from_metadata_prefers_gemini_token_counts():
    usage = usage_from_metadata(
        "gemini-2.5-flash-lite",
        SimpleNamespace(prompt_token_count=1200, candidates_token_count=300),
        prompt_chars=10_000,
        response_chars=2_000,
    )

    assert usage.input_tokens == 1200
    assert usage.output_tokens == 300
    assert usage.is_estimated is False
    assert usage.estimated_cost_usd == 0.00024


def test_usage_from_metadata_falls_back_to_character_estimate():
    usage = usage_from_metadata(
        "gemini-2.5-flash-lite",
        None,
        prompt_chars=4000,
        response_chars=400,
    )

    assert usage.input_tokens == estimate_tokens_from_chars(4000)
    assert usage.output_tokens == estimate_tokens_from_chars(400)
    assert usage.is_estimated is True
