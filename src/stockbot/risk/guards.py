"""Auto-stop conditions for unattended operation (spec §7.12). Any trip pauses new buys."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from stockbot.config import RiskConfig
from stockbot.market_calendar import KST, is_market_open, trading_days_between

if TYPE_CHECKING:
    from stockbot.risk.rules import OrderIntent

GuardCode = Literal["DAILY_ORDER_LIMIT", "CHURN", "CONSECUTIVE_LOSSES", "BAD_QUOTE", "DATA_STALE", "LEDGER_MISMATCH"]


class GuardTrip(BaseModel):
    code: GuardCode
    message: str


class FillRecord(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    qty: int
    price: float
    filled_at: datetime


def check_quote(price: float, quote_time: datetime, now: datetime, prev_close: float,
                cfg: RiskConfig | None = None) -> GuardTrip | None:
    cfg = cfg or RiskConfig()
    if price is None or price <= 0:
        return GuardTrip(code="BAD_QUOTE", message=f"비정상 시세: {price}")
    if prev_close and abs(price / prev_close - 1) > cfg.quote_jump_pct:
        return GuardTrip(code="BAD_QUOTE", message=f"전일 대비 {price / prev_close - 1:+.0%} 급변 시세 (확인 필요)")
    if is_market_open(now) and now - quote_time > timedelta(minutes=cfg.quote_stale_minutes):
        return GuardTrip(code="DATA_STALE", message=f"시세가 {int((now - quote_time).total_seconds() // 60)}분 지연됨")
    return None


def check_daily_limits(today_orders: list["OrderIntent"], prices: dict[str, float], budget_usd: float,
                       cfg: RiskConfig) -> GuardTrip | None:
    if len(today_orders) > cfg.max_orders_per_day:
        return GuardTrip(code="DAILY_ORDER_LIMIT", message=f"하루 주문 {len(today_orders)}건 > {cfg.max_orders_per_day}건")
    notional = sum(o.qty * (prices.get(o.ticker) or o.limit_price or 0) for o in today_orders)
    if notional > cfg.max_daily_notional_pct * budget_usd:
        return GuardTrip(code="DAILY_ORDER_LIMIT",
                         message=f"하루 주문금액 ${notional:,.0f} > 투입금의 {cfg.max_daily_notional_pct:.0%}")
    return None


def check_churn(fills: list[FillRecord], as_of: date, cfg: RiskConfig) -> GuardTrip | None:
    by_t: dict[str, list[FillRecord]] = defaultdict(list)
    for f in sorted(fills, key=lambda f: f.filled_at):
        by_t[f.ticker].append(f)
    for t, fs in by_t.items():
        trips, bought = 0, False
        for f in fs:
            d = f.filled_at.astimezone(KST).date() if f.filled_at.tzinfo else f.filled_at.date()
            recent = trading_days_between(d, as_of) <= cfg.churn_window_days
            if f.side == "buy":
                bought = True
            elif bought:
                bought = False
                if recent:
                    trips += 1
        if trips >= cfg.churn_round_trips:
            return GuardTrip(code="CHURN", message=f"{t}: {cfg.churn_window_days}거래일 내 {trips}회 왕복 매매")
    return None


def check_consecutive_losses(closed_trade_pnls: list[float], cfg: RiskConfig) -> GuardTrip | None:
    n = cfg.max_consecutive_losses
    tail = closed_trade_pnls[-n:]
    if len(tail) == n and all(p < 0 for p in tail):
        return GuardTrip(code="CONSECUTIVE_LOSSES", message=f"연속 {n}회 손실 청산")
    return None


def check_ledger(book: dict[str, int], broker: dict[str, int]) -> GuardTrip | None:
    diff = {t for t in set(book) | set(broker) if book.get(t, 0) != broker.get(t, 0)}
    if diff:
        return GuardTrip(code="LEDGER_MISMATCH", message="봇 장부와 브로커 잔고 불일치: " + ", ".join(sorted(diff)))
    return None
