from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class PositionView(BaseModel):
    ticker: str
    qty: int
    avg_price: float
    last_price: float

    @property
    def value(self) -> float:
        return self.qty * self.last_price

    @property
    def pnl_pct(self) -> float:
        return self.last_price / self.avg_price - 1 if self.avg_price else 0.0


class PortfolioView(BaseModel):
    cash: float
    positions: dict[str, PositionView] = {}
    peak_equity: float

    @property
    def equity(self) -> float:
        return self.cash + sum(p.value for p in self.positions.values())

    @property
    def invested(self) -> float:
        return sum(p.value for p in self.positions.values())


class MarketView(Protocol):
    def last_price(self, ticker: str) -> float: ...
    def adv_usd(self, ticker: str) -> float: ...
    def adv_shares(self, ticker: str) -> float: ...
