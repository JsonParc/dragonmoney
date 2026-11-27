from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Callable, Literal

from pydantic import BaseModel

from stockbot.config import DebateConfig
from stockbot.debate.prompts import referee_prompt, seat_prompt
from stockbot.debate.schema import (
    DIRECTION_OF,
    Action,
    Direction,
    Opinion,
    OpinionBody,
    PersuasionRecord,
    ResolvedAction,
)
from stockbot.debate.seats import REFEREE_ID, Seat
from stockbot.debate.tally import detect_persuasion, direction_vote, resolve_details, team_position
from stockbot.llm.base import LLMError
from stockbot.llm.router import LLMRouter, complete_json
from stockbot.models import DebateRow, OpinionRow
from stockbot.risk.portfolio import PositionView


class DebateContext(BaseModel):
    ticker: str
    sector: str
    as_of: date
    kind: Literal["regular", "emergency"] = "regular"
    holding: PositionView | None = None
    last_price: float
    chart_signals: list[str] = []
    indicator_summary: dict[str, float] = {}
    chart_png: bytes | None = None
    news_digest: list[str] = []
    macro_digest: list[str] = []
    case_digest: str | None = None
    scoreboard_text: str = ""
    anonymize: bool = False
    product_note: str | None = None
    fundamentals_digest: list[str] = []


class DebateResult(BaseModel):
    ticker: str
    as_of: date
    kind: str
    rounds: list[list[Opinion]]
    direction: Direction | None
    shares: dict[Direction, float]
    resolved: ResolvedAction | None
    deadlock: bool
    persuasion: PersuasionRecord
    invalid_seats: list[str]
    referee_summary: str
    held: bool = False


def _coerce(body: OpinionBody, held: bool) -> OpinionBody:
    """Map actions that make no sense for the position (e.g. SELL when not held) to the nearest valid one."""
    if not held and DIRECTION_OF[body.action] == Direction.SELL_SIDE:
        return body.model_copy(update={"action": Action.HOLD})
    if not held and body.action == Action.ADD:
        return body.model_copy(update={"action": Action.BUY})
    if held and body.action == Action.BUY:
        return body.model_copy(update={"action": Action.ADD})
    return body


class DebateEngine:
    def __init__(self, seats: list[Seat], router: LLMRouter, cfg: DebateConfig,
                 now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.seats = seats
        self.router = router
        self.cfg = cfg
        self.now_fn = now_fn

    def _ask(self, seat: Seat, ctx: DebateContext, rnd: int, prior: list[Opinion]) -> Opinion:
        req = seat_prompt(seat, ctx, rnd, prior)
        try:
            body, _ = complete_json(self.router, seat.seat_id, req, OpinionBody, self.now_fn())
        except LLMError:
            body = None
        if body is None:
            return Opinion(seat_id=seat.seat_id, team=seat.team, round=rnd, valid=False, action=Action.HOLD,
                           confidence=0.0, rationale="응답 실패/형식 오류 (기권 처리)")
        body = _coerce(body, ctx.holding is not None)
        return Opinion(**body.model_dump(), seat_id=seat.seat_id, team=seat.team, round=rnd)

    def _round(self, ctx: DebateContext, rnd: int, prior: list[Opinion]) -> list[Opinion]:
        with ThreadPoolExecutor(max_workers=len(self.seats)) as pool:
            return list(pool.map(lambda s: self._ask(s, ctx, rnd, prior), self.seats))

    def _quorum(self, ops: list[Opinion]) -> bool:
        valid = [o for o in ops if o.valid]
        return len(valid) >= self.cfg.min_valid_seats and {o.team for o in valid} == {s.team for s in self.seats}

    def run(self, ctx: DebateContext, weights: dict[str, float], max_rounds: int | None = None) -> DebateResult:
        limit = self.cfg.max_rebuttal_rounds if max_rounds is None else max_rounds
        rounds = [self._round(ctx, 0, [])]
        quorum = self._quorum(rounds[0])
        direction, shares = direction_vote(rounds[0], weights)
        pos = [team_position(rounds[0], weights, t) for t in {s.team for s in self.seats}]
        agreed = quorum and direction is not None and len(set(pos)) == 1 and pos[0] is not None
        if not agreed:
            direction = None
            for rnd in range(1, limit + 1):
                if not quorum:
                    break
                rounds.append(self._round(ctx, rnd, rounds[-1]))
                quorum = self._quorum(rounds[-1])
                if not quorum:
                    break
                direction, shares = direction_vote(rounds[-1], weights)
                if direction is not None:
                    break
        final = rounds[-1]
        any_valid = any(o.valid for o in final)
        deadlock = direction is None and quorum
        resolved = resolve_details(final, weights, direction) if direction is not None else None
        invalid = sorted({o.seat_id for r in rounds for o in r if not o.valid})
        summary = ""
        if any_valid:
            try:
                summary = self.router.complete(REFEREE_ID, referee_prompt(ctx, final, direction, deadlock),
                                               self.now_fn()).text.strip()
            except LLMError:
                summary = ""
        return DebateResult(ticker=ctx.ticker, as_of=ctx.as_of, kind=ctx.kind, rounds=rounds, direction=direction,
                            shares=shares, resolved=resolved, deadlock=deadlock,
                            persuasion=detect_persuasion(rounds[0], final, direction), invalid_seats=invalid,
                            referee_summary=summary, held=ctx.holding is not None)


def save_result(session, result: DebateResult) -> int:
    row = DebateRow(ticker=result.ticker, as_of=result.as_of, kind=result.kind,
                    direction=result.direction.value if result.direction else None, deadlock=result.deadlock,
                    persuading_team=result.persuasion.persuading_team.value if result.persuasion.persuading_team else None,
                    referee_summary=result.referee_summary, result_json=json.loads(result.model_dump_json()),
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None))
    session.add(row)
    session.flush()
    for rnd in result.rounds:
        for o in rnd:
            session.add(OpinionRow(debate_id=row.id, seat_id=o.seat_id, team=o.team.value, round=o.round,
                                   valid=o.valid, body_json=json.loads(o.model_dump_json())))
    session.flush()
    return row.id
