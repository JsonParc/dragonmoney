"""Shared helpers for the orders table (used by executor and brokers)."""
from __future__ import annotations

from datetime import datetime, timezone

from stockbot.models import OrderRow
from stockbot.risk.rules import OrderIntent


def naive_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts.astimezone(timezone.utc).replace(tzinfo=None) if ts.tzinfo else ts


def aware_utc(ts: datetime | None) -> datetime | None:
    return ts.replace(tzinfo=timezone.utc) if ts is not None and ts.tzinfo is None else ts


def row_from_intent(i: OrderIntent, status: str, needs_approval: bool, broker: str = "") -> OrderRow:
    return OrderRow(idempotency_key=i.idempotency_key, ticker=i.ticker, side=i.side, qty=i.qty, kind=i.kind,
                    limit_price=i.limit_price, expires_at=naive_utc(i.expires_at), status=status,
                    decision_id=i.decision_id, reason=i.reason, needs_approval=needs_approval,
                    created_at=naive_utc(datetime.now(timezone.utc)), broker=broker)


def intent_from_row(r: OrderRow) -> OrderIntent:
    return OrderIntent(ticker=r.ticker, side=r.side, qty=r.qty, kind=r.kind, limit_price=r.limit_price,
                       expires_at=aware_utc(r.expires_at), decision_id=r.decision_id, reason=r.reason or "",
                       idempotency_key=r.idempotency_key)
