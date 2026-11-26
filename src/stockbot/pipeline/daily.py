"""The daily cycle: post-close debates -> staged orders -> execution at the open (spec §7.8)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from pydantic import BaseModel

from stockbot.data.prices import MACRO_TICKERS, SECTOR_ETFS
from stockbot.debate.engine import save_result
from stockbot.market_calendar import next_trading_day, trading_session
from stockbot.pipeline.context import PriceMarket, build_context, portfolio_view, relevant_clusters
from stockbot.pipeline.news_watch import ingest_news
from stockbot.risk.guards import check_churn, check_consecutive_losses, check_daily_limits
from stockbot.risk.rules import apply_risk, circuit_breaker_tripped, decision_to_intents, forced_stop_losses
from stockbot.settings_store import get_kv, set_kv
from stockbot.signals.screener import screen
from stockbot.data.universe import sector_of

HISTORY_DAYS = 420


class CycleReport(BaseModel):
    debates: list[int] = []
    staged: list[int] = []
    rejected: list[tuple[str, str]] = []
    paused: bool = False
    notes: list[str] = []


def run_debate(deps, ticker: str, as_of: date, kind: str, pf, mkt, cfg, news_as_of: datetime | None = None):
    """Debate one ticker, persist it, and return (debate_id, intents)."""
    ctx = build_context(deps, ticker, as_of, kind, pf.positions.get(ticker), news_as_of)
    result = deps.engine.run(ctx, deps.scoreboard.weights())
    with deps.session_factory() as s:
        did = save_result(s, result)
        s.commit()
    dec = deps.scoreboard.record_debate(did, result, ref_price=ctx.last_price)
    intents = decision_to_intents(result, dec, pf, mkt, cfg.budget_usd, cfg.risk, as_of) if dec else []
    return did, result, intents


def cap_daily_buys(intents, mkt, cfg):
    """Keep buys (in priority order) until the daily notional cap; the rest wait for another day."""
    cap = cfg.risk.max_daily_notional_pct * cfg.budget_usd
    used, kept, dropped = 0.0, [], []
    for i in intents:
        if i.side == "sell":
            kept.append(i)
            continue
        cost = i.qty * (i.limit_price or mkt.last_price(i.ticker))
        if used + cost <= cap:
            used += cost
            kept.append(i)
        else:
            dropped.append((i, f"하루 매수 한도(투입금의 {cfg.risk.max_daily_notional_pct:.0%}) 초과로 보류"))
    return kept, dropped


class DailyCycle:
    def __init__(self, deps):
        self.d = deps

    def _refresh(self, session_date: date, now: datetime, held: list[str]) -> None:
        d = self.d
        tickers = sorted(set(d.universe) | set(held) | set(MACRO_TICKERS.values()) | set(SECTOR_ETFS.values()))
        try:
            d.prices.ensure(tickers, session_date - timedelta(days=HISTORY_DAYS), session_date)
            d.health.record("prices", True, f"{len(tickers)} tickers", now)
        except Exception as e:
            d.health.record("prices", False, str(e), now)
        ingest_news(d, now, held)

    def _guards(self, session_date: date, now: datetime, pf, cfg) -> list[str]:
        d = self.d
        trips = []
        fills = d.broker.fills_since(now - timedelta(days=14))
        for t in (check_churn(fills, session_date, cfg.risk),
                  check_consecutive_losses(d.broker.realized_pnls() if hasattr(d.broker, "realized_pnls") else [],
                                           cfg.risk)):
            if t:
                trips.append(t.message)
        if circuit_breaker_tripped(pf, cfg.risk):
            trips.append(f"서킷브레이커: 고점 대비 {pf.equity / pf.peak_equity - 1:+.1%}")
        return trips

    def _recent_orders(self, now: datetime) -> list:
        from sqlalchemy import select

        from stockbot.models import OrderRow
        from stockbot.orders_store import intent_from_row, naive_utc

        with self.d.session_factory() as s:
            rows = s.execute(select(OrderRow).where(OrderRow.created_at >= naive_utc(now - timedelta(hours=24)),
                                                    OrderRow.side == "buy",
                                                    OrderRow.status.in_(["staged", "filled", "open"]))).scalars().all()
            out = []
            for r in rows:
                i = intent_from_row(r)
                if i.limit_price is None:
                    i.limit_price = r.fill_price
                out.append(i)
            return out

    def _pause(self, cfg, reasons: list[str]) -> None:
        if not cfg.mode.paused:
            cfg.mode.paused = True
            cfg.mode.pause_reason = "; ".join(reasons)
            self.d.save_runtime(cfg)
            self.d.notifier.send("⛔ 자동 정지: 신규 매수를 멈췄습니다.\n사유: " + cfg.mode.pause_reason +
                                 "\n확인 후 /resume (PIN) 으로 재개하세요.")

    def _budget_alert(self, now: datetime) -> None:
        state = self.d.budget.state(now)
        with self.d.session_factory() as s:
            prev = get_kv(s, "budget_state", "ok")
            if state != prev:
                set_kv(s, "budget_state", state)
                s.commit()
        if state != prev and state in ("alert", "capped"):
            spend, cap = self.d.budget.month_spend(now), self.d.budget.cfg.monthly_cap_usd
            extra = " — 유료 모델 호출을 멈추고 무료 모델만 씁니다." if state == "capped" else ""
            self.d.notifier.send(f"💸 이번 달 AI 비용 ${spend:.2f} / ${cap:.0f} ({spend / cap:.0%}){extra}")

    def post_close(self, session_date: date, now: datetime) -> CycleReport:
        d, rep = self.d, CycleReport()
        cfg = d.runtime()
        held = list(d.broker.positions())
        self._refresh(session_date, now, held)
        d.scoreboard.grade_due(session_date, d.prices.close_on)
        mkt = PriceMarket(d.prices, session_date)
        pf = portfolio_view(d, mkt)

        intents = forced_stop_losses(pf, cfg.risk, session_date)
        severity = {}
        for t in pf.positions:
            cl = [c for c in relevant_clusters(d, t, sector_of(t), now) if c.verification == "confirmed"]
            severity[t] = max((c.severity for c in cl), default=0)
        stopped = {i.ticker for i in intents}
        for cand in screen(session_date, d.universe, pf.positions, d.prices, severity, cfg.budget_usd, cfg):
            if cand.ticker in stopped:
                continue
            try:
                did, _, ints = run_debate(d, cand.ticker, session_date, "regular", pf, mkt, cfg)
            except Exception as e:
                d.health.record("debate", False, f"{cand.ticker}: {e}", now)
                continue
            rep.debates.append(did)
            intents += ints

        trips = self._guards(session_date, now, pf, cfg)
        lim = check_daily_limits(self._recent_orders(now), {}, cfg.budget_usd, cfg.risk)
        if lim:
            trips.append(lim.message)
        if trips:
            self._pause(cfg, trips)
        rep.paused = cfg.mode.paused
        if d.health.degraded():
            rep.notes.append("데이터/LLM 장애 지속: 신규 매수 제외 (" + ", ".join(d.health.failing()) + ")")
            intents = [i for i in intents if i.side == "sell"]
        out = apply_risk(intents, pf, mkt, cfg.budget_usd, cfg.risk, cfg.mode, circuit_breaker_tripped(pf, cfg.risk))
        accepted, capped = cap_daily_buys(out.accepted, mkt, cfg)
        rep.rejected = [(i.ticker, why) for i, why in out.rejected] + [(i.ticker, why) for i, why in capped]
        out.accepted = accepted
        expires = trading_session(next_trading_day(session_date)).open_kst
        staged = d.executor.stage(out.accepted, cfg.mode, cfg.rebuy_auto, expires)
        rep.staged = staged.staged_ids
        self._snapshot(session_date, pf)
        self._budget_alert(now)
        return rep

    def _snapshot(self, session_date: date, pf) -> None:
        from stockbot.models import EquitySnapshot

        try:
            spy = self.d.prices.close_on(MACRO_TICKERS["spy"], session_date)
        except KeyError:
            spy = None
        with self.d.session_factory() as s:
            s.merge(EquitySnapshot(date=session_date, equity=pf.equity, cash=pf.cash, spy_close=spy))
            s.commit()

    def pre_open(self, session_date: date, now: datetime) -> list[int]:
        from stockbot.pipeline.news_watch import NewsWatcher

        return NewsWatcher(self.d).poll(now)

    def at_open(self, session_date: date, now: datetime):
        results = self.d.executor.execute_ready(now)
        results += self.d.broker.process_open_orders(now)
        filled = [r for r in results if r.status == "filled"]
        if filled:
            lines = [f"- {r.ticker} {'매수' if r.side == 'buy' else '매도'} {r.fill_qty}주 @ ${r.fill_price:,.2f}"
                     for r in filled]
            self.d.notifier.send("✅ 체결 완료\n" + "\n".join(lines))
        bad = [r for r in results if r.status == "rejected"]
        if bad:
            self.d.notifier.send("⚠️ 주문 거절\n" + "\n".join(f"- {r.ticker}: {r.message}" for r in bad))
        return results
