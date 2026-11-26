from datetime import datetime, timezone

import pytest
from llm_fakes import ScriptedClient
from pydantic import BaseModel

from stockbot.config import CostConfig, RuntimeConfig, Settings
from stockbot.llm.base import AllProvidersFailed, LLMError, LLMRequest, LLMResponse, RateLimited
from stockbot.llm.budget import BudgetTracker
from stockbot.llm.cache import CachedClient
from stockbot.llm.router import LLMRouter, build_router, complete_json

NOW = datetime(2026, 12, 1, 6, 30, tzinfo=timezone.utc)


def req(**kw):
    return LLMRequest(system="sys", user=kw.pop("user", "hello"), **kw)


def resp(cost):
    return LLMResponse(text="x", provider="p", model="m", input_tokens=1, output_tokens=1, cost_usd=cost)


class V(BaseModel):
    v: int


@pytest.fixture
def budget(session_factory):
    return BudgetTracker(session_factory, CostConfig())


@pytest.fixture
def budget_at_cap(budget):
    budget.record(resp(10.0), NOW)
    return budget


def free_budget():
    class _B:
        def allow(self, c, now): return True
        def record(self, r, now): pass
    return _B()


def test_cache_hit(session_factory):
    inner = ScriptedClient(['{"a":1}'], cost=0.01)
    c = CachedClient(inner, session_factory)
    c.complete(req())
    r2 = c.complete(req())
    assert len(inner.calls) == 1 and r2.cached and r2.cost_usd == 0


def test_cache_key_includes_image(session_factory):
    inner = ScriptedClient(['{"a":1}'])
    c = CachedClient(inner, session_factory)
    c.complete(req(image_png=b"one"))
    c.complete(req(image_png=b"two"))
    assert len(inner.calls) == 2


def test_router_falls_back_on_rate_limit(budget):
    a = ScriptedClient([RateLimited("429")])
    b = ScriptedClient(['{"x":1}'])
    r = LLMRouter({"s": [a, b]}, budget).complete("s", req(), NOW)
    assert r.text == '{"x":1}' and len(a.calls) == 1


def test_budget_blocks_paid_not_free(budget_at_cap):
    paid = ScriptedClient(["p"], is_free=False)
    free = ScriptedClient(["f"])
    assert LLMRouter({"s": [paid, free]}, budget_at_cap).complete("s", req(), NOW).text == "f"
    assert paid.calls == []


def test_budget_state(budget):  # cap 10
    budget.record(resp(8.5), NOW)
    assert budget.state(NOW) == "alert"
    budget.record(resp(2.0), NOW)
    assert budget.state(NOW) == "capped"
    assert budget.state(NOW.replace(year=2027, month=1)) == "ok"


def test_router_records_spend(budget):
    paid = ScriptedClient(["p"], is_free=False, cost=0.25)
    LLMRouter({"s": [paid]}, budget).complete("s", req(), NOW)
    assert budget.month_spend(NOW) == pytest.approx(0.25)


def test_complete_json_retries_once():
    c = ScriptedClient(["not json", '```json\n{"v": 2}\n```'])
    obj, _ = complete_json(LLMRouter({"s": [c]}, free_budget()), "s", req(), V, NOW)
    assert obj.v == 2 and len(c.calls) == 2 and "JSON" in c.calls[1].user


def test_complete_json_gives_up_after_retry():
    c = ScriptedClient(["nope", "still nope"])
    obj, last = complete_json(LLMRouter({"s": [c]}, free_budget()), "s", req(), V, NOW)
    assert obj is None and last.text == "still nope"


def test_image_dropped_for_text_only_model():
    c = ScriptedClient(["{}"], supports_image=False)
    LLMRouter({"s": [c]}, free_budget()).complete("s", req(image_png=b"png"), NOW)
    assert c.calls[0].image_png is None


def test_all_fail_raises():
    with pytest.raises(AllProvidersFailed):
        LLMRouter({"s": [ScriptedClient([LLMError("boom")])]}, free_budget()).complete("s", req(), NOW)


def test_unknown_seat_raises():
    with pytest.raises(AllProvidersFailed):
        LLMRouter({}, free_budget()).complete("nope", req(), NOW)


def test_build_router_uses_only_configured_providers(session_factory, monkeypatch):
    s = Settings(_env_file=None, web_password="p", pin="1", secret_key="k", groq_key="g")
    r = build_router(s, RuntimeConfig(), session_factory)
    for seat in ["chart_trend", "chart_volume", "chart_candle", "news_news", "news_case", "news_macro",
                 "referee", "reporter"]:
        chain = r.chains[seat]
        assert chain and all(c.provider == "groq" for c in chain)


@pytest.mark.network
def test_live_providers_return_json(session_factory):
    try:
        s = Settings()
    except Exception:
        pytest.skip("no .env")
    r = build_router(s, RuntimeConfig(), session_factory)
    seats = [k for k, v in r.chains.items() if v]
    if not seats:
        pytest.skip("no LLM keys configured")
    obj, resp = complete_json(r, seats[0], req(user='Return {"v": 7} as JSON.'), V, datetime.now(timezone.utc))
    assert obj is not None and obj.v == 7, resp
