from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from stockbot.risk.guards import FillRecord
from stockbot.risk.portfolio import PositionView
from stockbot.risk.rules import OrderIntent


class Quote(BaseModel):
    ticker: str
    price: float
    ts: datetime
    prev_close: float


class OrderResult(BaseModel):
    status: Literal["filled", "open", "rejected", "expired"]
    fill_price: float | None = None
    fill_qty: int = 0
    order_id: int
    ticker: str = ""
    side: str = ""
    message: str = ""


class Broker(Protocol):
    name: str

    def get_quote(self, ticker: str) -> Quote: ...
    def place(self, intent: OrderIntent, now: datetime) -> OrderResult: ...
    def positions(self) -> dict[str, PositionView]: ...
    def cash(self) -> float: ...
    def process_open_orders(self, now: datetime) -> list[OrderResult]: ...
    def fills_since(self, since: datetime) -> list[FillRecord]: ...
