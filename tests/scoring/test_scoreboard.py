from datetime import date

import pytest
from engine_helpers import CHART, NEWS, SEAT_IDS

from stockbot.config import DebateConfig
from stockbot.debate.engine import DebateResult
from stockbot.debate.schema import Action, Direction, Opinion, PersuasionRecord, ResolvedAction, Team
from stockbot.models import ScoreEvent
from stockbot.scoring.scoreboard import Scoreboard, grade, update_weight

D = date(2024, 6, 3)  # Monday


def _ops(actions, rnd):
    out = []
    for seat, action in actions.items():
        team = Team.CHART if seat in CHART else Team.NEWS
        out.append(Opinion(seat_id=seat, team=team, round=rnd, action=Action(action), confidence=0.7, rationale="r"))
    return out


def persuaded_result(direction=Direction.BUY_SIDE, team=Team.CHART):
    r0 = _ops({**{c: "BUY" for c in CHART}, **{n: "HOLD" for n in NEWS}}, 0)
    fin = _ops({**{c: "BUY" for c in CHART}, "news_news": "BUY", "news_case": "HOLD", "news_macro": "HOLD"}, 1)
    return DebateResult(ticker="T", as_of=D, kind="regular", rounds=[r0, fin], direction=direction,
                        shares={d: 0.0 for d in Direction}, resolved=ResolvedAction(action=Action.BUY),
                        deadlock=False, persuasion=PersuasionRecord(persuading_team=team, switched_seats=["news_news"]),
                        invalid_seats=[], referee_summary="")


def deadlock_result():
    fin = _ops({**{c: "BUY" for c in CHART}, **{n: "SELL" for n in NEWS}}, 2)
    return DebateResult(ticker="T", as_of=D, kind="regular", rounds=[fin], direction=None,
                        shares={d: 0.0 for d in Direction}, resolved=None, deadlock=True,
                        persuasion=PersuasionRecord(), invalid_seats=[], referee_summary="")


@pytest.fixture
def board(session_factory):
    b = Scoreboard(session_factory, DebateConfig(), SEAT_IDS)
    b._sf_ = session_factory
    return b


def board_events(board, seat):
    with board._sf_() as s:
        return s.query(ScoreEvent).filter_by(seat_id=seat).all()


def test_grade():
    cfg = DebateConfig()
    assert grade(Direction.BUY_SIDE, 0.01, cfg) == "correct" and grade(Direction.BUY_SIDE, -0.01, cfg) == "wrong"
    assert grade(Direction.SELL_SIDE, 0.003, cfg) == "neutral" and grade(Direction.HOLD, 0.03, cfg) == "wrong"
    assert grade(Direction.HOLD, 0.01, cfg) == "correct"


def test_update_weight_and_clamp():
    ema, w = update_weight(0.0, 3.0, DebateConfig())
    assert ema == pytest.approx(0.6) and w == pytest.approx(1.3)
    for _ in range(20):
        ema, w = update_weight(ema, 3.0, DebateConfig())
    assert w == 1.5
    for _ in range(40):
        ema, w = update_weight(ema, -3.0, DebateConfig())
    assert w == 0.5


def test_weights_default_to_one(board):
    assert board.weights() == {s: 1.0 for s in SEAT_IDS}


def test_persuasion_bonus_only_when_correct(board):
    did = board.record_debate(1, persuaded_result(Direction.BUY_SIDE, Team.CHART), ref_price=100)
    graded = board.grade_due(date(2024, 6, 10), close_on=lambda t, d: 103.0)  # 5 trading days later, +3%
    assert graded == [did]
    assert {e.delta for e in board_events(board, "chart_trend")} >= {1.0, 2.0}
    assert board.weights()["chart_trend"] > 1.0
    assert -1.0 in {e.delta for e in board_events(board, "news_case")}  # HOLD while price moved 3%


def test_persuasion_penalty_when_wrong(board):
    board.record_debate(1, persuaded_result(Direction.BUY_SIDE, Team.CHART), 100)
    board.grade_due(date(2024, 6, 10), close_on=lambda t, d: 97.0)
    assert -2.0 in {e.delta for e in board_events(board, "chart_trend")}


def test_not_graded_before_horizon(board):
    board.record_debate(1, persuaded_result(Direction.BUY_SIDE, Team.CHART), 100)
    assert board.grade_due(date(2024, 6, 7), close_on=lambda t, d: 103.0) == []


def test_graded_only_once(board):
    board.record_debate(1, persuaded_result(), 100)
    board.grade_due(date(2024, 6, 10), close_on=lambda t, d: 103.0)
    assert board.grade_due(date(2024, 6, 11), close_on=lambda t, d: 103.0) == []


def test_deadlock_penalizes_everyone(board):
    assert board.record_debate(2, deadlock_result(), 100) is None
    assert all(board.weights()[s] < 1.0 for s in SEAT_IDS)


def test_summary_text(board):
    board.record_debate(1, persuaded_result(), 100)
    board.grade_due(date(2024, 6, 10), close_on=lambda t, d: 103.0)
    text = board.summary_text()
    assert "chart_trend" in text and "가중치" in text
