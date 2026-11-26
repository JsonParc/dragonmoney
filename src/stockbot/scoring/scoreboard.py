"""Outcome-verified scoreboard: seats earn points only when the market proves them right (spec §7.6)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Callable, Literal

from sqlalchemy import select

from stockbot.config import DebateConfig
from stockbot.debate.engine import DebateResult
from stockbot.debate.schema import DIRECTION_OF, Direction
from stockbot.market_calendar import add_trading_days, trading_days_between
from stockbot.models import DecisionRow, ScoreEvent, SeatScore

Outcome = Literal["correct", "wrong", "neutral"]


def grade(direction: Direction, ret: float, cfg: DebateConfig) -> Outcome:
    if direction == Direction.BUY_SIDE:
        return "correct" if ret > cfg.neutral_threshold else "wrong" if ret < -cfg.neutral_threshold else "neutral"
    if direction == Direction.SELL_SIDE:
        return "correct" if ret < -cfg.neutral_threshold else "wrong" if ret > cfg.neutral_threshold else "neutral"
    return "correct" if abs(ret) <= cfg.hold_band else "wrong"


def update_weight(ema: float, delta: float, cfg: DebateConfig) -> tuple[float, float]:
    ema2 = (1 - cfg.weight_ema_alpha) * ema + cfg.weight_ema_alpha * delta
    w = min(cfg.weight_max, max(cfg.weight_min, 1 + cfg.weight_k * ema2))
    return ema2, w


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Scoreboard:
    def __init__(self, session_factory, cfg: DebateConfig, seat_ids: list[str]):
        self._sf = session_factory
        self.cfg = cfg
        self.seat_ids = seat_ids

    def weights(self) -> dict[str, float]:
        with self._sf() as s:
            rows = {r.seat_id: r.weight for r in s.execute(select(SeatScore)).scalars()}
        return {seat: rows.get(seat, 1.0) for seat in self.seat_ids}

    def _apply(self, s, debate_id: int | None, deltas: list[tuple[str, float, str]]) -> None:
        agg: dict[str, float] = defaultdict(float)
        for seat, delta, reason in deltas:
            s.add(ScoreEvent(seat_id=seat, debate_id=debate_id, delta=delta, reason=reason, created_at=_now()))
            agg[seat] += delta
        for seat, total in agg.items():
            row = s.get(SeatScore, seat) or SeatScore(seat_id=seat, ema=0.0, weight=1.0, n=0)
            row.ema, row.weight = update_weight(row.ema, total, self.cfg)
            row.n += 1
            s.merge(row)

    def record_debate(self, debate_id: int, result: DebateResult, ref_price: float) -> int | None:
        deltas: list[tuple[str, float, str]] = []
        if result.deadlock:
            deltas += [(seat, -self.cfg.deadlock_penalty, "deadlock") for seat in self.seat_ids]
        deltas += [(seat, -self.cfg.invalid_penalty, "invalid") for seat in result.invalid_seats]
        with self._sf() as s:
            self._apply(s, debate_id, deltas)
            decision_id = None
            if result.direction is not None:
                final = {o.seat_id: DIRECTION_OF[o.action].value for o in result.rounds[-1] if o.valid}
                team_of = {o.seat_id: o.team.value for o in result.rounds[-1]}
                row = DecisionRow(debate_id=debate_id, ticker=result.ticker, as_of=result.as_of,
                                  direction=result.direction.value, ref_price=ref_price, graded=False,
                                  persuading_team=(result.persuasion.persuading_team.value
                                                   if result.persuasion.persuading_team else None),
                                  seat_directions=final, seat_teams=team_of)
                s.add(row)
                s.flush()
                decision_id = row.id
            s.commit()
        return decision_id

    def grade_due(self, as_of: date, close_on: Callable[[str, date], float]) -> list[int]:
        h = self.cfg.grading_horizon_days
        graded: list[int] = []
        with self._sf() as s:
            due = [d for d in s.execute(select(DecisionRow).where(DecisionRow.graded.is_(False))).scalars()
                   if trading_days_between(d.as_of, as_of) >= h]
            for d in due:
                exit_price = close_on(d.ticker, add_trading_days(d.as_of, h))
                ret = exit_price / d.ref_price - 1 if d.ref_price else 0.0
                outcome = grade(Direction(d.direction), ret, self.cfg)
                deltas: list[tuple[str, float, str]] = []
                for seat, sd in (d.seat_directions or {}).items():
                    o = grade(Direction(sd), ret, self.cfg)
                    if o != "neutral":
                        deltas.append((seat, self.cfg.individual_point * (1 if o == "correct" else -1), "individual"))
                if d.persuading_team and outcome != "neutral":
                    pts = self.cfg.bonus if outcome == "correct" else -self.cfg.persuasion_penalty
                    deltas += [(seat, pts, "persuasion") for seat, t in (d.seat_teams or {}).items()
                               if t == d.persuading_team]
                self._apply(s, d.debate_id, deltas)
                d.graded, d.outcome, d.ret = True, outcome, ret
                graded.append(d.id)
            s.commit()
        return graded

    def summary_text(self) -> str:
        w = self.weights()
        lines = []
        with self._sf() as s:
            for seat in self.seat_ids:
                ev = s.execute(select(ScoreEvent.delta).where(ScoreEvent.seat_id == seat, ScoreEvent.reason == "individual")
                               .order_by(ScoreEvent.id.desc()).limit(20)).scalars().all()
                hits = sum(1 for x in ev if x > 0)
                rate = f"최근 {len(ev)}건 적중 {hits}" if ev else "채점 기록 없음"
                lines.append(f"- {seat}: 가중치 {w[seat]:.2f}, {rate}")
        return "\n".join(lines)
