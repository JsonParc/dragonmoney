from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select

from stockbot.models import ApprovalRowDB, OrderRow
from stockbot.orders_store import aware_utc, naive_utc

Decision = Literal["ok", "expired", "already"]


class ApprovalRow(BaseModel):
    id: int
    order_id: int
    status: str
    expires_at: datetime
    ticker: str = ""
    side: str = ""
    qty: int = 0
    kind: str = ""
    reason: str = ""
    decision_id: int | None = None


class ApprovalQueue:
    def __init__(self, session_factory):
        self._sf = session_factory

    def create(self, order_id: int, expires_at: datetime) -> int:
        with self._sf() as s:
            row = ApprovalRowDB(order_id=order_id, status="pending", expires_at=naive_utc(expires_at))
            s.add(row)
            s.commit()
            return row.id

    def _decide(self, approval_id: int, now: datetime, status: str) -> Decision:
        with self._sf() as s:
            row = s.get(ApprovalRowDB, approval_id)
            if row is None or row.status != "pending":
                return "already" if row is None or row.status != "expired" else "expired"
            if naive_utc(now) >= row.expires_at:
                row.status = "expired"
                s.commit()
                return "expired"
            row.status, row.decided_at = status, naive_utc(now)
            s.commit()
            return "ok"

    def approve(self, approval_id: int, now: datetime) -> Decision:
        return self._decide(approval_id, now, "approved")

    def reject(self, approval_id: int, now: datetime) -> Decision:
        return self._decide(approval_id, now, "rejected")

    def get(self, approval_id: int) -> ApprovalRow | None:
        with self._sf() as s:
            a = s.get(ApprovalRowDB, approval_id)
            return self._view(s, a) if a else None

    @staticmethod
    def _view(s, a: ApprovalRowDB) -> ApprovalRow:
        o = s.get(OrderRow, a.order_id)
        return ApprovalRow(id=a.id, order_id=a.order_id, status=a.status, expires_at=aware_utc(a.expires_at),
                           ticker=o.ticker if o else "", side=o.side if o else "", qty=o.qty if o else 0,
                           kind=o.kind if o else "", reason=(o.reason or "") if o else "",
                           decision_id=o.decision_id if o else None)

    def pending(self, now: datetime) -> list[ApprovalRow]:
        with self._sf() as s:
            rows = s.execute(select(ApprovalRowDB).where(ApprovalRowDB.status == "pending",
                                                         ApprovalRowDB.expires_at > naive_utc(now))).scalars().all()
            return [self._view(s, a) for a in rows]

    def expire(self, now: datetime) -> list[int]:
        with self._sf() as s:
            rows = s.execute(select(ApprovalRowDB).where(ApprovalRowDB.status == "pending",
                                                         ApprovalRowDB.expires_at <= naive_utc(now))).scalars().all()
            for r in rows:
                r.status = "expired"
            s.commit()
            return [r.id for r in rows]

    def status_by_order(self) -> dict[int, str]:
        with self._sf() as s:
            return {a.order_id: a.status for a in s.execute(select(ApprovalRowDB)).scalars()}
