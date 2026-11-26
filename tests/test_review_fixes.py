"""Regression tests for the final-review findings (one section per finding)."""
import threading
from datetime import date, datetime, timedelta, timezone

import pytest
from engine_helpers import SEAT_IDS, W1, body, ctx, engine, scripted_router
from exec_helpers import quotes
from fastapi.testclient import TestClient
from news_helpers import item
from pipe_fakes import MARKET_OPEN_NOW, NOW, OPEN, SESSION, hold, make_deps, news, series, staged_orders

from stockbot.broker.base import Quote
from stockbot.broker.paper import PaperBroker
from stockbot.config import ModeState, RiskConfig, RuntimeConfig
from stockbot.data.verify import verify
from stockbot.debate.schema import Action
from stockbot.llm.base import LLMError
from stockbot.models import OrderRow
from stockbot.pipeline.daily import DailyCycle
from stockbot.pipeline.news_watch import NewsWatcher
from stockbot.risk.rules import OrderIntent, apply_risk, decision_to_intents
from stockbot.scheduler import catch_up, plan_jobs
from stockbot.sentiment.impact import assess
from stockbot.telegram.commands import CommandService
from stockbot.web.app import create_app

PREV_CLOSE_TS = OPEN - timedelta(hours=17, minutes=30)


def _buy(t, qty, key, kind="new_buy", **kw):
    return OrderIntent(ticker=t, side="buy", qty=qty, kind=kind, reason="t", idempotency_key=key, **kw)


# 2. quotes at the opening bell still carry the previous close's timestamp
def test_stale_quote_at_open_is_deferred_not_rejected(session_factory):
    p = PaperBroker(session_factory, quotes(100.0, ts=PREV_CLOSE_TS), initial_cash=10_000)
    r = p.place(_buy("T", 1, "k1"), OPEN + timedelta(minutes=5))
    assert r.status == "deferred"
    with session_factory() as s:
        assert s.query(OrderRow).filter_by(idempotency_key="k1").one().status == "staged"
    p.quote_fn = quotes(100.0, ts=OPEN + timedelta(minutes=19))
    assert p.place(_buy("T", 1, "k1"), OPEN + timedelta(minutes=20)).status == "filled"


def test_open_jobs_run_after_the_bell_with_retries():
    jobs = [j for j in plan_jobs(date(2026, 12, 2), RuntimeConfig()) if j.name in ("open", "open_retry")]
    o = datetime(2026, 12, 2, 23, 30, tzinfo=OPEN.tzinfo)
    assert [j.run_at - o for j in jobs] == [timedelta(minutes=5), timedelta(minutes=20), timedelta(minutes=45)]


# 3. a bad quote pauses new buys and alerts
def test_bad_quote_at_open_pauses_and_alerts():
    d = make_deps(automation="auto")
    DailyCycle(d).post_close(SESSION, NOW)
    d.broker.quote_fn = lambda t: Quote(ticker=t, price=0.0, ts=OPEN, prev_close=100.0)
    DailyCycle(d).at_open(SESSION, OPEN + timedelta(minutes=5))
    assert d.runtime().mode.paused and any("시세" in m.text and "정지" in m.text for m in d.notifier.messages)


# 4. pause is enforced at execution time, not only at staging
def test_paused_between_staging_and_open_blocks_buys():
    d = make_deps(automation="auto")
    DailyCycle(d).post_close(SESSION, NOW)
    cfg = d.runtime(); cfg.mode.paused = True; d.save_runtime(cfg)
    d.clock.now = OPEN
    DailyCycle(d).at_open(SESSION, OPEN + timedelta(minutes=5))
    with d.session_factory() as s:
        assert s.query(OrderRow).filter(OrderRow.side == "buy", OrderRow.status == "filled",
                                        OrderRow.idempotency_key.notlike("seed:%")).count() == 0


def test_paused_blocks_resting_rebuy_fill(session_factory):
    p = PaperBroker(session_factory, quotes(95.0, 89.0), initial_cash=10_000)
    p.place(_buy("T", 10, "rb", kind="rebuy", limit_price=90, expires_at=OPEN + timedelta(days=30)), OPEN)
    assert p.process_open_orders(OPEN + timedelta(hours=1), allow_buys=False) == []
    assert "T" not in p.positions()


# 5. stale staged orders expire; pending buys count against limits; missed jobs are caught up
def test_staged_orders_expire_after_their_session(executor_deps=None):
    d = make_deps(automation="auto")
    DailyCycle(d).post_close(SESSION, NOW)
    n = len(staged_orders(d))
    later = OPEN + timedelta(days=1, hours=12)
    d.clock.now = later
    res = d.executor.execute_ready(later)
    assert n > 0 and res == [] and staged_orders(d) == []


def test_pending_buys_count_against_limits():
    m_pf = (RuntimeConfig().risk,)
    from risk_helpers import empty_pf, mkt
    pending = [_buy("A", 20, "p1")]
    out = apply_risk([_buy("A", 20, "new")], empty_pf(10_000), mkt(100), 10_000, RiskConfig(), ModeState(), False,
                     pending=pending)
    assert out.accepted == []  # 20 pending + 20 new = $4,000 > 20% per-ticker cap


def test_catch_up_runs_missed_post_close():
    d = make_deps()
    ran = catch_up(d, DailyCycle(d), NOW + timedelta(hours=3))
    assert ("post_close", SESSION) in ran
    assert catch_up(d, DailyCycle(d), NOW + timedelta(hours=4)) == []


# 6. health: occasional debate errors and failing report jobs must not block buying forever
def test_health_ignores_job_components_and_recovers():
    d = make_deps()
    for _ in range(3):
        d.health.record("job:report", False, "x", NOW)
    assert not d.health.degraded()
    for _ in range(3):
        d.health.record("debate", False, "x", NOW)
    assert d.health.degraded()
    d.health.record("debate", True, "ok", NOW)
    assert not d.health.degraded()


# 7. quorum: one surviving seat must not decide alone
def test_quorum_required():
    held = ctx().holding
    script = {s: [LLMError("429")] for s in SEAT_IDS}
    script["news_news"] = [body("SELL")]
    from stockbot.risk.portfolio import PositionView
    res = engine(scripted_router(script)).run(ctx(holding=PositionView(ticker="NVDA", qty=5, avg_price=100, last_price=100)), W1)
    assert res.direction is None and res.resolved is None and not res.deadlock


# 8. a PIN typed without a pending request is never forwarded to an LLM
def test_pin_never_forwarded():
    from llm_fakes import ScriptedClient
    from stockbot.llm.router import LLMRouter

    class _Free:
        def allow(self, c, now): return True
        def record(self, r, now): pass
    d = make_deps()
    client = ScriptedClient(["answer"])
    d.router = LLMRouter({"reporter": [client]}, _Free())
    svc = CommandService(d, d.settings)
    r = svc.handle_text(111, "1234", NOW)
    assert client.calls == [] and "PIN" in r.text
    svc.handle_text(111, "987654", NOW)
    assert client.calls == []


# 9. "denies approval" is real bad news, not a rumor rebuttal; company shocks are severe
def test_fda_denial_is_not_contradiction():
    g = [item(domain="reuters.com", title="FDA denies approval of Acme's cancer drug"),
         item(domain="cnbc.com", title="FDA denies approval for Acme cancer drug")]
    assert verify(g) == "confirmed"


def test_company_shocks_reach_threshold():
    for title in ("Acme files for Chapter 11 bankruptcy", "SEC charges Acme with accounting fraud",
                  "FDA rejects Acme's lead drug"):
        it = assess(item(title=title, tickers=["ACME"]), -0.8)
        assert it.severity >= 4, title


# 10. a failed emergency debate is retried on the next poll
def test_failed_emergency_is_retried():
    d = make_deps(script={s: [LLMError("down")] for s in SEAT_IDS}, frames={"NVDA": series(100, 100)})
    hold(d, "NVDA")
    d.clock.now = MARKET_OPEN_NOW
    w = NewsWatcher(d)
    d.news_sources[0].queue(news("War breaks out, oil prices surge 12%", "cnbc.com"),
                            news("War breaks out as oil prices surge 12 percent", "marketwatch.com"))
    w.poll(MARKET_OPEN_NOW)
    for seat in SEAT_IDS:
        d.engine.router.chains[seat][0].responses = [body("SELL")]
    assert len(w.poll(MARKET_OPEN_NOW + timedelta(minutes=10))) == 1


# 11. concurrent executions never send the same staged row twice
def test_concurrent_execute_ready_fills_once():
    d = make_deps(automation="auto")
    DailyCycle(d).post_close(SESSION, NOW)
    d.clock.now = OPEN + timedelta(minutes=5)
    n = len(staged_orders(d))
    results = []
    ts = [threading.Thread(target=lambda: results.append(d.executor.execute_ready(OPEN + timedelta(minutes=5))))
          for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    with d.session_factory() as s:
        filled = s.query(OrderRow).filter(OrderRow.status == "filled", OrderRow.idempotency_key.notlike("seed:%")).count()
    assert filled == n


# 12. limit buys fill at the better price; LLM rebuy prices above market are clamped
def test_limit_fills_at_market_when_lower(session_factory):
    p = PaperBroker(session_factory, quotes(80.0), initial_cash=10_000)
    r = p.place(_buy("T", 1, "lim", kind="rebuy", limit_price=90, expires_at=OPEN + timedelta(days=5)), NOW)
    assert r.fill_price == 80.0


def test_rebuy_price_clamped_below_market():
    from risk_helpers import D, mkt, pf_with, res
    ints = decision_to_intents(res("SELL_REBUY", rebuy_price=120), 4, pf_with("T", 10, 100, 100), mkt(100),
                               10_000, RiskConfig(), D)
    assert ints[1].limit_price < 100


# 13. Monday's report covers Friday's session
def test_monday_report_uses_previous_trading_day():
    rep = next(j for j in plan_jobs(date(2026, 11, 30), RuntimeConfig()) if j.name == "report")
    assert rep.session_date == date(2026, 11, 27)


# 14. risk/cost/seat edits need the PIN; PIN guessing is rate-limited
@pytest.fixture
def web():
    d = make_deps()
    c = TestClient(create_app(d, d.settings, now_fn=lambda: NOW))
    c.post("/api/login", json={"password": "pw"})
    return d, c


def test_risk_and_cost_edits_need_pin(web):
    d, c = web
    assert c.patch("/api/settings", json={"risk": {"circuit_breaker_dd": -1.0}}).status_code == 403
    assert c.patch("/api/settings", json={"cost": {"monthly_cap_usd": 500}}).status_code == 403
    assert c.patch("/api/settings", json={"mode": {"paused": True}}).status_code == 200  # stopping stays easy


def test_pin_attempts_are_limited(web):
    d, c = web
    for _ in range(5):
        c.patch("/api/settings", json={"budget_usd": 1, "pin": "0000"})
    assert c.patch("/api/settings", json={"budget_usd": 1, "pin": "1234"}).status_code == 429
