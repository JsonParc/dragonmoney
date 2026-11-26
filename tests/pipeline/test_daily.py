from datetime import timedelta

from engine_helpers import SEAT_IDS, body
from pipe_fakes import NOW, OPEN, SESSION, make_deps, staged_orders

from stockbot.llm.base import LLMResponse
from stockbot.models import OrderRow
from stockbot.pipeline.daily import DailyCycle
from stockbot.risk.rules import OrderIntent
from stockbot.settings_store import load_runtime


def test_post_close_debates_only_screened():
    deps = make_deps()
    rep = DailyCycle(deps).post_close(SESSION, NOW)
    assert len(rep.debates) == 5 and rep.staged  # 7 bullish tickers, top 5 debated


def test_daily_buy_cap_trims_instead_of_pausing():
    deps = make_deps()
    rep = DailyCycle(deps).post_close(SESSION, NOW)
    buys = [o for o in staged_orders(deps) if o.side == "buy"]
    assert not rep.paused and 0 < len(buys) < 5
    assert sum(o.qty * 101 for o in buys) <= 0.30 * 10_000
    assert any("하루 매수 한도" in why for _, why in rep.rejected)


def test_semi_mode_buys_wait_for_approval():
    deps = make_deps()
    DailyCycle(deps).post_close(SESSION, NOW)
    assert all(o.needs_approval for o in staged_orders(deps) if o.side == "buy")
    assert any(m.buttons for m in deps.notifier.messages)


def test_degraded_health_blocks_buys():
    deps = make_deps()

    class DeadSource:
        def fetch(self, since, tickers):
            raise RuntimeError("feed down")
    deps.news_sources = [DeadSource()]
    for _ in range(2):
        deps.health.record("news", False, "x", NOW)
    rep = DailyCycle(deps).post_close(SESSION, NOW)  # third consecutive news failure -> degraded
    assert rep.debates and all(o.side == "sell" for o in staged_orders(deps))
    assert any("장애" in n for n in rep.notes)


def test_guard_trip_pauses_and_notifies():
    deps = make_deps()
    for k in range(3):  # three round trips on UP3 inside the window
        for side in ("buy", "sell"):
            deps.broker.place(OrderIntent(ticker="UP3", side=side, qty=1, kind="new_buy" if side == "buy" else "sell",
                                          reason="x", idempotency_key=f"churn:{k}:{side}"), NOW - timedelta(days=1))
    rep = DailyCycle(deps).post_close(SESSION, NOW)
    assert rep.paused and any("자동 정지" in m.text for m in deps.notifier.messages)
    with deps.session_factory() as s:
        assert load_runtime(s).mode.paused
    assert all(o.side == "sell" for o in staged_orders(deps))


def test_open_rerun_does_not_duplicate():
    deps = make_deps(automation="auto")
    c = DailyCycle(deps)
    c.post_close(SESSION, NOW)
    n_staged = len(staged_orders(deps))
    deps.clock.now = OPEN
    c.at_open(SESSION, OPEN)
    c.at_open(SESSION, OPEN)
    with deps.session_factory() as s:
        filled = s.query(OrderRow).filter(OrderRow.status == "filled").count()
    assert n_staged > 0 and filled == n_staged


def test_budget_alert_notifies_once():
    deps = make_deps()
    deps.budget.record(LLMResponse(text="", provider="p", model="m", cost_usd=8.5), NOW)
    c = DailyCycle(deps)
    c.post_close(SESSION, NOW)
    c.post_close(SESSION, NOW + timedelta(hours=1))
    assert sum("AI 비용" in m.text for m in deps.notifier.messages) == 1


def test_price_failure_recorded_in_health():
    deps = make_deps()

    class Boom:
        def fetch(self, *a):
            raise RuntimeError("yahoo down")
    deps.prices._fetcher = Boom()
    deps.prices._sf = deps.session_factory
    DailyCycle(deps).post_close(SESSION, NOW)
    assert deps.health.status()["prices"]["ok"] is False
