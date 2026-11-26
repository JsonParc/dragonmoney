from datetime import date

from engine_helpers import CHART, NEWS, SEAT_IDS, SEATS, W1, body, ctx, engine, scripted_router

from stockbot.debate.engine import save_result
from stockbot.debate.prompts import seat_prompt
from stockbot.debate.schema import Action, Direction, Team
from stockbot.llm.base import LLMError
from stockbot.models import DebateRow, OpinionRow
from stockbot.risk.portfolio import PositionView


def test_agreement_ends_after_round0():
    r = scripted_router({s: [body("BUY")] for s in SEAT_IDS}, referee=["요약"])
    res = engine(r).run(ctx(), W1)
    assert len(res.rounds) == 1 and res.direction == Direction.BUY_SIDE and r.calls_for("chart_trend") == 1
    assert res.resolved.action == Action.BUY and res.referee_summary == "요약" and not res.deadlock


def test_persuasion_in_rebuttal():
    script = {**{c: [body("BUY"), body("BUY")] for c in CHART}, "news_news": [body("SELL"), body("BUY")],
              "news_case": [body("SELL"), body("SELL")], "news_macro": [body("SELL"), body("SELL")]}
    held = PositionView(ticker="NVDA", qty=10, avg_price=90, last_price=100)
    res = engine(scripted_router(script)).run(ctx(holding=held), W1)
    assert res.direction == Direction.BUY_SIDE and res.persuasion.persuading_team == Team.CHART
    assert res.persuasion.switched_seats == ["news_news"] and len(res.rounds) == 2


def test_deadlock_after_max_rounds():
    script = {**{c: [body("BUY")] * 3 for c in CHART}, **{n: [body("SELL")] * 3 for n in NEWS}}
    held = PositionView(ticker="NVDA", qty=10, avg_price=90, last_price=100)
    res = engine(scripted_router(script)).run(ctx(holding=held), W1)
    assert res.deadlock and res.direction is None and len(res.rounds) == 3


def test_invalid_seat_abstains():
    held = PositionView(ticker="NVDA", qty=10, avg_price=90, last_price=100)
    script = {**{s: [body("SELL")] for s in SEAT_IDS}, "chart_trend": ["garbage", "still garbage"]}
    res = engine(scripted_router(script)).run(ctx(holding=held), W1)
    assert "chart_trend" in res.invalid_seats and res.direction == Direction.SELL_SIDE


def test_all_providers_down_yields_no_trade():
    res = engine(scripted_router({s: [LLMError("down")] for s in SEAT_IDS})).run(ctx(), W1)
    assert res.direction is None and set(res.invalid_seats) == set(SEAT_IDS) and not res.deadlock


def test_sell_without_holding_becomes_hold():
    res = engine(scripted_router({s: [body("SELL")] for s in SEAT_IDS})).run(ctx(), W1)
    assert res.direction == Direction.HOLD


def test_team_inputs_are_separated():
    req_c = seat_prompt(SEATS["chart_trend"], ctx(news_digest=["WAR NEWS"]), 0, [])
    req_n = seat_prompt(SEATS["news_news"], ctx(chart_png=b"png"), 0, [])
    assert "WAR NEWS" not in req_c.user and req_n.image_png is None
    assert seat_prompt(SEATS["chart_trend"], ctx(chart_png=b"png"), 0, []).image_png == b"png"


def test_rebuttal_prompt_shows_other_team():
    r0 = engine(scripted_router({**{c: [body("BUY")] for c in CHART}, **{n: [body("SELL", rationale="WAR RISK")] for n in NEWS}}))
    res = r0.run(ctx(holding=PositionView(ticker="NVDA", qty=1, avg_price=1, last_price=1)), W1, max_rounds=1)
    req = seat_prompt(SEATS["chart_trend"], ctx(), 1, res.rounds[0])
    assert "WAR RISK" in req.user


def test_anonymize():
    req = seat_prompt(SEATS["news_news"], ctx(ticker="NVDA", as_of=date(2024, 8, 5),
                                              news_digest=["NVDA falls on 2024-08-05"], anonymize=True), 0, [])
    assert "NVDA" not in req.user and "2024-08-05" not in req.user and "종목 A" in req.user


def test_save_result(session_factory):
    res = engine(scripted_router({s: [body("BUY")] for s in SEAT_IDS})).run(ctx(), W1)
    with session_factory() as s:
        did = save_result(s, res)
        s.commit()
        assert s.get(DebateRow, did).direction == "buy_side"
        assert s.query(OpinionRow).filter_by(debate_id=did).count() == 6


def test_leveraged_product_warning_in_prompt():
    req = seat_prompt(SEATS["chart_trend"], ctx(ticker="TQQQ", product_note="3배 레버리지 ETF"), 0, [])
    assert "3배 레버리지 ETF" in req.user and "감쇠" in req.user
