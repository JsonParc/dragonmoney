"""Stages order intents (with approval where needed) and sends ready ones to the broker."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import select

from stockbot.broker.base import Broker, OrderResult
from stockbot.config import ModeState
from stockbot.execution.approvals import ApprovalQueue
from stockbot.execution.routing import route
from stockbot.models import OrderRow
from stockbot.notify import Notifier
from stockbot.orders_store import intent_from_row, row_from_intent
from stockbot.risk.rules import OrderIntent

KIND_KO = {"new_buy": "신규 매수", "add": "추가 매수", "rebuy": "되사기", "switch_buy": "교체 매수",
           "sell": "매도", "trim": "일부 매도", "stop_loss": "손절", "switch_sell": "교체 매도"}


class StageReport(BaseModel):
    staged_ids: list[int] = []
    approval_ids: list[int] = []
    duplicates: int = 0


class Executor:
    def __init__(self, session_factory, broker: Broker, approvals: ApprovalQueue, notifier: Notifier):
        self._sf = session_factory
        self.broker = broker
        self.approvals = approvals
        self.notifier = notifier

    def stage(self, intents: list[OrderIntent], mode: ModeState, rebuy_auto: bool,
              approval_expires_at: datetime) -> StageReport:
        auto, need = route(intents, mode, rebuy_auto)
        rep = StageReport()
        pending_msgs: list[tuple[int, OrderIntent]] = []
        with self._sf() as s:
            for i, needs in [(x, False) for x in auto] + [(x, True) for x in need]:
                if s.execute(select(OrderRow.id).where(OrderRow.idempotency_key == i.idempotency_key)).first():
                    rep.duplicates += 1
                    continue
                row = row_from_intent(i, "staged", needs)
                s.add(row)
                s.flush()
                rep.staged_ids.append(row.id)
                if needs:
                    pending_msgs.append((row.id, i))
            s.commit()
        for order_id, i in pending_msgs:
            aid = self.approvals.create(order_id, approval_expires_at)
            rep.approval_ids.append(aid)
            price = f" 지정가 ${i.limit_price:,.2f}" if i.limit_price else ""
            self.notifier.send(
                f"🟡 승인 요청 #{aid}: {i.ticker} {i.qty}주 {KIND_KO.get(i.kind, i.kind)}{price}\n근거: {i.reason}\n"
                f"오늘 장 시작 전까지 승인하지 않으면 실행되지 않습니다.",
                buttons=[("승인", f"approve:{aid}"), ("거절", f"reject:{aid}"), ("자세히", f"detail:{order_id}")])
        return rep

    def execute_ready(self, now: datetime) -> list[OrderResult]:
        self.approvals.expire(now)
        status = self.approvals.status_by_order()
        with self._sf() as s:
            rows = s.execute(select(OrderRow).where(OrderRow.status == "staged")).scalars().all()
            ready, dead = [], []
            for r in rows:
                if not r.needs_approval or status.get(r.id) == "approved":
                    ready.append(r)
                elif status.get(r.id) in ("expired", "rejected"):
                    dead.append(r)
            for r in dead:
                r.status, r.message = "expired" if status.get(r.id) == "expired" else "rejected", "미승인"
            s.commit()
            intents = [intent_from_row(r) for r in sorted(ready, key=lambda r: (r.side != "sell", r.id))]
        return [self.broker.place(i, now) for i in intents]

    def execute_now(self, intents: list[OrderIntent], now: datetime) -> list[OrderResult]:
        self.stage(intents, ModeState(automation="auto"), True, now)
        keys = {i.idempotency_key for i in intents}
        with self._sf() as s:
            rows = s.execute(select(OrderRow).where(OrderRow.status == "staged",
                                                    OrderRow.idempotency_key.in_(keys))).scalars().all()
            ordered = [intent_from_row(r) for r in sorted(rows, key=lambda r: (r.side != "sell", r.id))]
        return [self.broker.place(i, now) for i in ordered]
