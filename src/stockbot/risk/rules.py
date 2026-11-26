"""Hard risk rules in code. They override whatever the debate decided (spec §7.7)."""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from stockbot.config import ModeState, RiskConfig, TradingRules
from stockbot.debate.engine import DebateResult
from stockbot.debate.schema import Action
from stockbot.data.universe import etf_info
from stockbot.market_calendar import add_trading_days, trading_session
from stockbot.risk.liquidity import affordable, liquidity_ok
from stockbot.risk.portfolio import MarketView, PortfolioView

OrderKind = Literal["new_buy", "add", "rebuy", "trim", "sell", "stop_loss", "switch_sell", "switch_buy"]
BUY_KINDS = {"new_buy", "add", "rebuy", "switch_buy"}
REBUY_EXPIRY_DAYS = 20
DEFAULT_BUY_PCT = 0.10


class OrderIntent(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    qty: int
    kind: OrderKind
    limit_price: float | None = None
    expires_at: datetime | None = None
    decision_id: int | None = None
    reason: str
    idempotency_key: str


class RiskOutcome(BaseModel):
    accepted: list[OrderIntent] = []
    rejected: list[tuple[OrderIntent, str]] = []


def _buy_qty(pct: float | None, price: float, held_value: float, budget: float, cfg: RiskConfig) -> int:
    frac = min(pct if pct else DEFAULT_BUY_PCT, cfg.max_position_pct)
    amount = frac * budget - held_value
    return max(0, math.floor(amount / price)) if price > 0 else 0


def decision_to_intents(result: DebateResult, decision_id: int, pf: PortfolioView, mkt: MarketView,
                        budget_usd: float, cfg: RiskConfig, as_of: date) -> list[OrderIntent]:
    r = result.resolved
    if r is None or r.action == Action.HOLD:
        return []
    t = result.ticker
    pos = pf.positions.get(t)
    held = pos.qty if pos else 0
    price = mkt.last_price(t)
    reason = f"토론 결정 #{decision_id}: {r.action.value}"

    def intent(kind: OrderKind, side: str, qty: int, ticker: str = t, **kw) -> OrderIntent:
        return OrderIntent(ticker=ticker, side=side, qty=qty, kind=kind, decision_id=decision_id, reason=reason,
                           idempotency_key=f"{decision_id}:{kind}:{ticker}", **kw)

    if r.action in (Action.BUY, Action.ADD):
        qty = _buy_qty(r.size_pct, price, pos.value if pos else 0.0, budget_usd, cfg)
        return [intent("add" if held else "new_buy", "buy", qty)] if qty > 0 else []
    if held <= 0:
        return []
    if r.action == Action.TRIM:
        qty = max(1, math.floor(held * (r.size_pct or 0.5)))
        return [intent("trim", "sell", min(qty, held))]
    if r.action == Action.SELL:
        return [intent("sell", "sell", held)]
    if r.action == Action.SELL_REBUY:
        limit = r.rebuy_price or round(price * 0.95, 2)
        expires = trading_session(add_trading_days(as_of, REBUY_EXPIRY_DAYS)).close_kst
        return [intent("sell", "sell", held), intent("rebuy", "buy", held, limit_price=limit, expires_at=expires)]
    if r.action == Action.SWITCH:
        out = [intent("switch_sell", "sell", held)]
        if r.switch_to and r.switch_to != t:
            p2 = mkt.last_price(r.switch_to)
            q2 = _buy_qty(r.size_pct, p2, 0.0, budget_usd, cfg)
            if q2 > 0:
                out.append(intent("switch_buy", "buy", q2, ticker=r.switch_to))
        return out
    return []


def eligible(ticker: str, rules: TradingRules) -> tuple[bool, str]:
    """Product-type rules (ETF / leveraged-inverse ETF) for buys."""
    etf = etf_info(ticker)
    if etf is None:
        return True, ""
    if etf.is_leveraged:
        if rules.allow_leveraged_etf:
            return True, ""
        kind = "인버스" if etf.leverage < 0 else f"{etf.leverage}배 레버리지"
        return False, f"{kind} 상품 매수 비허용 (설정에서 레버리지·인버스 ETF 허용 필요)"
    if rules.allow_etf:
        return True, ""
    return False, "ETF 매수 비허용 (설정에서 ETF 허용 필요)"


def apply_risk(intents: list[OrderIntent], pf: PortfolioView, mkt: MarketView, budget_usd: float, cfg: RiskConfig,
               mode: ModeState, circuit_tripped: bool, rules: TradingRules | None = None) -> RiskOutcome:
    rules = rules or TradingRules()
    out = RiskOutcome()
    cash = pf.cash
    held = {t: p.qty for t, p in pf.positions.items()}
    invested = pf.invested
    sells = [i for i in intents if i.side == "sell"]
    buys = [i for i in intents if i.side == "buy"]

    for i in sells:
        have = held.get(i.ticker, 0)
        if have <= 0:
            out.rejected.append((i, "보유 수량 없음"))
            continue
        qty = min(i.qty, have)
        price = mkt.last_price(i.ticker)
        held[i.ticker] = have - qty
        cash += qty * price
        invested -= qty * price
        out.accepted.append(i.model_copy(update={"qty": qty}))

    for i in buys:
        if mode.paused:
            out.rejected.append((i, f"일시정지 중: {mode.pause_reason or '사용자 정지'}"))
            continue
        if circuit_tripped:
            out.rejected.append((i, "서킷브레이커 발동 중 (신규 매수 중단)"))
            continue
        ok, why = eligible(i.ticker, rules)
        if not ok:
            out.rejected.append((i, why))
            continue
        price = i.limit_price or mkt.last_price(i.ticker)
        if price <= 0:
            out.rejected.append((i, "가격 정보 없음"))
            continue
        if not affordable(price, budget_usd, cfg):
            out.rejected.append((i, f"1주 가격 ${price:,.2f}가 종목당 한도 초과"))
            continue
        is_new = held.get(i.ticker, 0) == 0
        n_holdings = sum(1 for q in held.values() if q > 0)
        if is_new and i.kind in ("new_buy", "switch_buy") and n_holdings >= cfg.max_holdings:
            out.rejected.append((i, f"보유 종목 수 한도({cfg.max_holdings}) 도달"))
            continue
        cur_value = held.get(i.ticker, 0) * mkt.last_price(i.ticker)
        room = min(budget_usd - invested, cash, cfg.max_position_pct * budget_usd - cur_value)
        qty = min(i.qty, math.floor(max(room, 0) / price))
        if qty <= 0:
            out.rejected.append((i, "투입금/현금/종목 비중 한도 초과"))
            continue
        ok, why = liquidity_ok(mkt.adv_usd(i.ticker), mkt.adv_shares(i.ticker), qty, cfg, rules.allow_low_volume)
        if not ok:
            out.rejected.append((i, why))
            continue
        cash -= qty * price
        invested += qty * price
        held[i.ticker] = held.get(i.ticker, 0) + qty
        out.accepted.append(i.model_copy(update={"qty": qty}))
    return out


def forced_stop_losses(pf: PortfolioView, cfg: RiskConfig, as_of: date) -> list[OrderIntent]:
    return [OrderIntent(ticker=t, side="sell", qty=p.qty, kind="stop_loss",
                        reason=f"강제 손절 ({p.pnl_pct:+.1%} ≤ {cfg.stop_loss_pct:.0%})",
                        idempotency_key=f"stop:{t}:{as_of.isoformat()}")
            for t, p in pf.positions.items() if p.qty > 0 and p.pnl_pct <= cfg.stop_loss_pct]


def circuit_breaker_tripped(pf: PortfolioView, cfg: RiskConfig) -> bool:
    return pf.peak_equity > 0 and pf.equity / pf.peak_equity - 1 <= cfg.circuit_breaker_dd
