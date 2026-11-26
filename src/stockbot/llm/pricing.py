"""Model ids and prices (USD per 1M tokens: input, output). Free-tier models cost 0.

Default ids are provisional (spike 2026-11-27 could not measure without keys) and can be
overridden in .env (STOCKBOT_*_MODEL) without code changes.
"""
from __future__ import annotations

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "gemini_lite": "gemini-2.5-flash-lite",
    "groq": "llama-3.3-70b-versatile",
    "groq_alt": "qwen/qwen3-32b",
    "groq_vision": "meta-llama/llama-4-scout-17b-16e-instruct",
    "openai": "gpt-5-mini",
    "anthropic": "claude-opus-5-5",
}

FREE_PROVIDERS = {"gemini", "gemini_lite", "groq", "groq_alt", "groq_vision"}
VISION_PROVIDERS = {"gemini", "gemini_lite", "groq_vision", "openai", "anthropic"}

MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "gpt-5-mini": (0.25, 2.00),
}


def price_of(model: str, free: bool) -> tuple[float, float]:
    return (0.0, 0.0) if free else MODEL_PRICES.get(model, (1.0, 5.0))


def cost(model: str, free: bool, tokens_in: int, tokens_out: int) -> float:
    pi, po = price_of(model, free)
    return (tokens_in * pi + tokens_out * po) / 1_000_000
