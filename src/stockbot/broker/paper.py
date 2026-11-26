"""Built-in paper broker: same engine for backtests and live paper trading."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from stockbot.broker.base import OrderResult, Quote
from stockbot.models import OrderRow, PaperCash, PaperPosition
from stockbot.orders_store import aware_utc, naive_utc, row_from_intent
from stockbot.risk.guards import FillRecord, check_quote
from stockbot.risk.portfolio import PositionView
from stockbot.risk.rules import OrderIntent

FINAL = {"filled", "rejected", "expired", "open", "cancelled", "executing"}


class PaperBroker:
    name = "paper"

    def __init__(self, session_factory, quote_fn: Callable[[str], Quote], initial_cash: float,
                 slippage_bps: float = 5, commission_rate: float = 0.0025):
        self._sf = session_factory
        self.quote_fn = quote_fn
        self.slip = slippage_bps / 10_000
        self.comm = commission_rate
        with self._sf() as s:
            if s.get(PaperCash, 1) is None:
                s.add(PaperCash(id=1, cash=initial_cash, peak_equity=initial_cash))
                s.commit()

    # ------------------------------------------------------------ queries
    def get_quote(self, ticker: str) -> Quote:
        return self.quote_fn(ticker)

    def cash(self) -> float:
        with self._sf() as s:
            return s.get(PaperCash, 1).cash

    def peak_equity(self) -> float:
        with self._sf() as s:
            return s.get(PaperCash, 1).peak_equity

    def update_peak(self, equity: float) -> float:
        with self._sf() as s:
            row = s.get(PaperCash, 1)
            row.peak_equity = max(row.peak_equity, equity)
            s.commit()
            return row.peak_equity

    def positions(self) -> dict[str, PositionView]:
        with self._sf() as s:
            return {p.ticker: PositionView(ticker=p.ticker, qty=p.qty, avg_price=p.avg_price, last_price=p.avg_price)
                    for p in s.execute(select(PaperPosition)).scalars() if p.qty > 0}

    def fills_since(self, since: datetime) -> list[FillRecord]:
        with self._sf() as s:
            rows = s.execute(select(OrderRow).where(OrderRow.status == "filled", OrderRow.broker == self.name,
                                                    OrderRow.filled_at >= naive_utc(since))
                             .order_by(OrderRow.filled_at, OrderRow.id)).scalars().all()
        return [FillRecord(ticker=r.ticker, side=r.side, qty=r.fill_qty, price=r.fill_price,
                           filled_at=aware_utc(r.filled_at)) for r in rows]

    def realized_pnls(self) -> list[float]:
        with self._sf() as s:
            return [r for r in s.execute(select(OrderRow.realized_pnl).where(
                OrderRow.status == "filled", OrderRow.side == "sell", OrderRow.broker == self.name,
                OrderRow.realized_pnl.is_not(None)).order_by(OrderRow.filled_at, OrderRow.id)).scalars()]

    # ------------------------------------------------------------ orders
    @staticmethod
    def _result(r: OrderRow) -> OrderResult:
        status = "deferred" if r.status in ("staged", "executing") else r.status
        return OrderResult(status=status, fill_price=r.fill_price, fill_qty=r.fill_qty or 0, order_id=r.id,
                           ticker=r.ticker, side=r.side, message=r.message or "", guard=r.guard_code)

    def _claim(self, intent: OrderIntent) -> int | None:
        """Atomically move the order to 'executing' (compare-and-set). Returns the row id if we own it."""
        with self._sf() as s:
            row = s.execute(select(OrderRow).where(OrderRow.idempotency_key == intent.idempotency_key)).scalar_one_or_none()
            if row is None:
                row = row_from_intent(intent, "executing", False, self.name)
                s.add(row)
                try:
                    s.commit()
                except IntegrityError:
                    return None
                return row.id
            res = s.execute(update(OrderRow).where(OrderRow.id == row.id, OrderRow.status == "staged")
                            .values(status="executing", broker=self.name))
            s.commit()
            return row.id if res.rowcount == 1 else None

    def place(self, intent: OrderIntent, now: datetime) -> OrderResult:
        oid = self._claim(intent)
        with self._sf() as s:
            if oid is None:
                row = s.execute(select(OrderRow).where(OrderRow.idempotency_key == intent.idempotency_key)).scalar_one()
                return self._result(row)
            row = s.get(OrderRow, oid)
            self._execute(s, row, now)
            if row.status == "executing":  # deferred (stale quote): retry on a later run
                row.status = "staged"
            s.commit()
            return self._result(row)

    def _execute(self, s, row: OrderRow, now: datetime) -> None:
        try:
            q = self.quote_fn(row.ticker)
        except Exception as e:  # data source failure
            row.status, row.message = "rejected", f"시세 조회 실패: {e}"
            return
        trip = check_quote(q.price, q.ts, now, q.prev_close)
        if trip and trip.code == "DATA_STALE":
            row.message, row.guard_code = trip.message, trip.code
            return
        if trip:
            row.status, row.message, row.guard_code = "rejected", trip.message, trip.code
            return
        if row.side == "buy" and row.limit_price is not None:
            if q.price <= row.limit_price:
                self._fill(s, row, min(row.limit_price, q.price), now)
            else:
                row.status, row.message = "open", f"지정가 {row.limit_price} 대기 (현재 {q.price})"
            return
        price = q.price * (1 + self.slip) if row.side == "buy" else q.price * (1 - self.slip)
        self._fill(s, row, price, now)

    def _fill(self, s, row: OrderRow, price: float, now: datetime) -> None:
        cash = s.get(PaperCash, 1)
        pos = s.get(PaperPosition, row.ticker)
        qty = row.qty
        if row.side == "buy":
            qty = min(qty, math.floor(cash.cash / (price * (1 + self.comm))))
            if qty <= 0:
                row.status, row.message = "rejected", "현금 부족"
                return
            fee = price * qty * self.comm
            cash.cash -= price * qty + fee
            if pos is None:
                pos = PaperPosition(ticker=row.ticker, qty=0, avg_price=0.0)
                s.add(pos)
            pos.avg_price = (pos.avg_price * pos.qty + price * qty) / (pos.qty + qty)
            pos.qty += qty
        else:
            have = pos.qty if pos else 0
            qty = min(qty, have)
            if qty <= 0:
                row.status, row.message = "rejected", "보유 수량 없음"
                return
            fee = price * qty * self.comm
            cash.cash += price * qty - fee
            row.realized_pnl = (price - pos.avg_price) * qty - fee
            pos.qty -= qty
        row.status, row.fill_price, row.fill_qty, row.commission = "filled", price, qty, fee
        row.filled_at = naive_utc(now)

    def process_open_orders(self, now: datetime, allow_buys: bool = True) -> list[OrderResult]:
        out: list[OrderResult] = []
        with self._sf() as s:
            rows = s.execute(select(OrderRow).where(OrderRow.status == "open", OrderRow.broker == self.name)).scalars().all()
            for r in rows:
                if r.expires_at is not None and naive_utc(now) > r.expires_at:
                    r.status, r.message = "expired", "지정가 미체결 만료"
                else:
                    if r.side == "buy" and not allow_buys:
                        continue
                    try:
                        q = self.quote_fn(r.ticker)
                    except Exception:
                        continue
                    if check_quote(q.price, q.ts, now, q.prev_close) or q.price > r.limit_price:
                        continue
                    self._fill(s, r, min(r.limit_price, q.price), now)
                out.append(self._result(r))
            s.commit()
        return out
