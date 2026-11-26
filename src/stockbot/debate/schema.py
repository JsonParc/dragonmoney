from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class Team(StrEnum):
    CHART = "chart"
    NEWS = "news"


class Action(StrEnum):
    BUY = "BUY"
    ADD = "ADD"
    HOLD = "HOLD"
    TRIM = "TRIM"
    SELL = "SELL"
    SELL_REBUY = "SELL_REBUY"
    SWITCH = "SWITCH"


class Direction(StrEnum):
    BUY_SIDE = "buy_side"
    HOLD = "hold"
    SELL_SIDE = "sell_side"


DIRECTION_OF: dict[Action, Direction] = {
    Action.BUY: Direction.BUY_SIDE,
    Action.ADD: Direction.BUY_SIDE,
    Action.HOLD: Direction.HOLD,
    Action.TRIM: Direction.SELL_SIDE,
    Action.SELL: Direction.SELL_SIDE,
    Action.SELL_REBUY: Direction.SELL_SIDE,
    Action.SWITCH: Direction.SELL_SIDE,
}


class OpinionBody(BaseModel):
    """The JSON object every seat must return."""

    action: Action
    confidence: float = Field(ge=0, le=1)
    size_pct: float | None = Field(default=None, ge=0, le=1)
    target_price: float | None = None
    rebuy_price: float | None = None
    expected_drop_pct: float | None = None
    horizon_days: int = 5
    switch_to: str | None = None
    rationale: str
    evidence: list[str] = []

    @field_validator("action", mode="before")
    @classmethod
    def _upper(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class Opinion(OpinionBody):
    seat_id: str
    team: Team
    round: int
    valid: bool = True

    @property
    def direction(self) -> Direction:
        return DIRECTION_OF[self.action]


class ResolvedAction(BaseModel):
    action: Action
    size_pct: float | None = None
    target_price: float | None = None
    rebuy_price: float | None = None
    switch_to: str | None = None


class PersuasionRecord(BaseModel):
    persuading_team: Team | None = None
    switched_seats: list[str] = []
