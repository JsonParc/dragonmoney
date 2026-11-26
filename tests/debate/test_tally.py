import pytest
from debate_helpers import CHART, NEWS, W1, C, N, op

from stockbot.debate.schema import DIRECTION_OF, Action, Direction, OpinionBody, Team
from stockbot.debate.tally import detect_persuasion, direction_vote, resolve_details, team_position


def test_direction_mapping():
    assert DIRECTION_OF[Action.ADD] == Direction.BUY_SIDE and DIRECTION_OF[Action.SWITCH] == Direction.SELL_SIDE
    assert DIRECTION_OF[Action.HOLD] == Direction.HOLD


def test_opinion_body_rejects_bad_confidence():
    with pytest.raises(ValueError):
        OpinionBody(action="BUY", confidence=1.5, rationale="x")


def test_split_three_ways_no_winner():
    ops = [op("c1", C, "BUY"), op("c2", C, "BUY"), op("c3", C, "HOLD"),
           op("n1", N, "SELL"), op("n2", N, "SELL"), op("n3", N, "HOLD")]
    assert team_position(ops, W1, C) == Direction.BUY_SIDE and team_position(ops, W1, N) == Direction.SELL_SIDE
    d, shares = direction_vote(ops, W1)
    assert d is None and shares[Direction.HOLD] == pytest.approx(1 / 3)


def test_team_tie_is_none():
    ops = [op("c1", C, "BUY"), op("c2", C, "SELL"), op("c3", C, "HOLD", valid=False)]
    assert team_position(ops, W1, C) is None


def test_exact_half_is_deadlock():
    ops = [op(s, C, "BUY") for s in CHART] + [op(s, N, "SELL") for s in NEWS]
    assert direction_vote(ops, W1)[0] is None


def test_weights_break_balance():
    w = {**{s: 1.5 for s in CHART}, **{s: 0.5 for s in NEWS}}
    ops = [op(s, C, "BUY") for s in CHART] + [op(s, N, "SELL") for s in NEWS]
    d, shares = direction_vote(ops, w)
    assert d == Direction.BUY_SIDE and shares[d] == pytest.approx(0.75)


def test_invalid_excluded_from_denominator():
    ops = [op("c1", C, "SELL"), op("c2", C, "SELL"), op("c3", C, "HOLD", valid=False),
           op("n1", N, "SELL"), op("n2", N, "HOLD"), op("n3", N, "HOLD", valid=False)]
    assert direction_vote(ops, W1)[0] == Direction.SELL_SIDE  # 3/4


def test_all_invalid_no_winner():
    ops = [op(s, C, "BUY", valid=False) for s in CHART]
    assert direction_vote(ops, W1)[0] is None


def test_resolve_details_weighted_median():
    ops = [op("c1", C, "TRIM", size_pct=0.5), op("n1", N, "SELL_REBUY", rebuy_price=90),
           op("n2", N, "SELL_REBUY", rebuy_price=94), op("n3", N, "SELL_REBUY", rebuy_price=100)]
    r = resolve_details(ops, W1, Direction.SELL_SIDE)
    assert r.action == Action.SELL_REBUY and r.rebuy_price == 94


def test_resolve_details_switch_target():
    ops = [op("n1", N, "SWITCH", switch_to="XOM"), op("n2", N, "SWITCH", switch_to="XOM"),
           op("n3", N, "SWITCH", switch_to="CVX")]
    assert resolve_details(ops, W1, Direction.SELL_SIDE).switch_to == "XOM"


def test_persuasion_detected():
    r0 = [op(s, C, "BUY") for s in CHART] + [op(s, N, "SELL") for s in NEWS]
    fin = [op(s, C, "BUY", round=1) for s in CHART] + [op("n1", N, "BUY", round=1), op("n2", N, "SELL", round=1),
                                                        op("n3", N, "SELL", round=1)]
    p = detect_persuasion(r0, fin, Direction.BUY_SIDE)
    assert p.persuading_team == Team.CHART and p.switched_seats == ["n1"]


def test_no_persuasion_when_teams_agreed():
    r0 = [op(s, C, "BUY") for s in CHART] + [op(s, N, "BUY") for s in NEWS]
    p = detect_persuasion(r0, r0, Direction.BUY_SIDE)
    assert p.persuading_team is None and p.switched_seats == []
