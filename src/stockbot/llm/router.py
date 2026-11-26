"""Per-seat provider chains with free-first fallback, budget enforcement and JSON helpers."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from stockbot.config import RuntimeConfig, Settings
from stockbot.llm.base import AllProvidersFailed, LLMClient, LLMError, LLMRequest, LLMResponse
from stockbot.llm.budget import BudgetTracker
from stockbot.llm.cache import CachedClient
from stockbot.llm.pricing import DEFAULT_MODELS, FREE_PROVIDERS, VISION_PROVIDERS

T = TypeVar("T", bound=BaseModel)

SEAT_IDS = ["chart_trend", "chart_volume", "chart_candle", "news_news", "news_case", "news_macro",
            "referee", "reporter"]

# Free-first chains per seat; providers within a team are mixed (spec §7.5). Paid providers go last.
DEFAULT_CHAINS: dict[str, list[str]] = {
    "chart_trend": ["gemini", "groq_vision", "groq"],
    "chart_volume": ["groq", "gemini_lite", "groq_alt"],
    "chart_candle": ["groq_vision", "gemini", "groq"],
    "news_news": ["groq", "gemini_lite", "groq_alt"],
    "news_case": ["gemini", "groq_alt", "groq"],
    "news_macro": ["groq_alt", "gemini_lite", "groq"],
    "referee": ["gemini", "groq", "gemini_lite"],
    "reporter": ["gemini", "groq", "gemini_lite"],
}
PAID_TAIL = ["openai", "anthropic"]


class LLMRouter:
    def __init__(self, chains: dict[str, list[LLMClient]], budget: BudgetTracker):
        self.chains = chains
        self.budget = budget

    def complete(self, seat_id: str, req: LLMRequest, now: datetime) -> LLMResponse:
        errors: list[str] = []
        for client in self.chains.get(seat_id, []):
            if not self.budget.allow(client, now):
                errors.append(f"{client.provider}: budget")
                continue
            r = req if (req.image_png is None or client.supports_image) else req.model_copy(update={"image_png": None})
            try:
                resp = client.complete(r)
            except LLMError as e:
                errors.append(f"{client.provider}: {type(e).__name__}")
                continue
            self.budget.record(resp, now)
            return resp
        raise AllProvidersFailed(f"seat {seat_id}: " + ("; ".join(errors) or "no providers"))


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.S)


def parse_json_text(text: str) -> dict | None:
    t = _FENCE.sub("", text.strip())
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                v = json.loads(m.group(0))
                return v if isinstance(v, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def complete_json(router: LLMRouter, seat_id: str, req: LLMRequest, model_cls: type[T],
                  now: datetime) -> tuple[T | None, LLMResponse | None]:
    last: LLMResponse | None = None
    for attempt in range(2):
        r = req if attempt == 0 else req.model_copy(
            update={"user": req.user + "\n\n중요: 설명 없이 JSON 객체 하나만 출력하세요. Output ONLY one JSON object."})
        last = router.complete(seat_id, r, now)
        data = parse_json_text(last.text)
        if data is not None:
            try:
                return model_cls.model_validate(data), last
            except ValidationError:
                pass
    return None, last


def _make_client(name: str, settings: Settings) -> LLMClient | None:
    from stockbot.llm.providers import GEMINI_BASE, GROQ_BASE, AnthropicClient, OpenAICompatClient

    model = getattr(settings, f"{name}_model", None) or DEFAULT_MODELS[name]
    free, vision = name in FREE_PROVIDERS, name in VISION_PROVIDERS
    if name.startswith("gemini") and settings.gemini_key:
        return OpenAICompatClient(name, GEMINI_BASE, settings.gemini_key, model, free, vision)
    if name.startswith("groq") and settings.groq_key:
        return OpenAICompatClient("groq", GROQ_BASE, settings.groq_key, model, free, vision)
    if name == "openai" and settings.openai_key:
        return OpenAICompatClient("openai", None, settings.openai_key, model, False, True)
    if name == "anthropic" and settings.anthropic_key:
        return AnthropicClient(settings.anthropic_key, model)
    return None


def build_router(settings: Settings, runtime_cfg: RuntimeConfig, session_factory) -> LLMRouter:
    overrides = {a.seat_id: a.providers for a in runtime_cfg.seats}
    built: dict[str, LLMClient | None] = {}
    chains: dict[str, list[LLMClient]] = {}
    for seat in SEAT_IDS:
        names = overrides.get(seat) or (DEFAULT_CHAINS[seat] + PAID_TAIL)
        chain: list[LLMClient] = []
        for n in names:
            if n not in built:
                c = _make_client(n, settings)
                built[n] = CachedClient(c, session_factory) if c else None
            if built[n] is not None and built[n] not in chain:
                chain.append(built[n])
        chains[seat] = chain
    return LLMRouter(chains, BudgetTracker(session_factory, runtime_cfg.cost))
