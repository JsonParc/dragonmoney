from datetime import timedelta

import pytest
from exec_helpers import NOW, buy, quotes, rebuy

from stockbot.broker.paper import PaperBroker
from stockbot.risk.rules import OrderIntent


@pytest.fixture
def paper(session_factory):
    return PaperBroker(session_factory, quotes(100.0), initial_cash=10_000)


def test_paper_fill_with_slippage_and_commission(paper):
    r = paper.place(buy("T", 10, key="k1"), NOW)
    assert r.status == "filled" and r.fill_price == pytest.approx(100.05)
    assert paper.cash() == pytest.approx(10_000 - 1000.5 - 2.50125)
    assert paper.positions()["T"].qty == 10


def test_sell_reduces_position(paper):
    paper.place(buy("T", 10, key="b"), NOW)
    r = paper.place(OrderIntent(ticker="T", side="sell", qty=4, kind="sell", reason="x", idempotency_key="s"), NOW)
    assert r.fill_price == pytest.approx(99.95) and paper.positions()["T"].qty == 6
    assert [f.side for f in paper.fills_since(NOW - timedelta(days=1))] == ["buy", "sell"]


def test_idempotent_order(paper):
    a = paper.place(buy("T", 10, key="same"), NOW)
    b = paper.place(buy("T", 10, key="same"), NOW)
    assert a.order_id == b.order_id and paper.positions()["T"].qty == 10


def test_buy_clipped_to_cash(session_factory):
    p = PaperBroker(session_factory, quotes(100.0), initial_cash=1_000)
    r = p.place(buy("T", 10, key="c"), NOW)
    assert r.fill_qty == 9 and p.cash() >= 0


def test_paper_broker_refuses_bad_quote(session_factory):
    p = PaperBroker(session_factory, quotes(0.0), initial_cash=10_000)
    assert p.place(buy("T", 1, key="z"), NOW).status == "rejected"


def test_resting_limit_rebuy(session_factory):
    p = PaperBroker(session_factory, quotes(95.0, 89.0), initial_cash=10_000)
    r = p.place(rebuy("T", 10, limit=90, expires=NOW + timedelta(days=30)), NOW)
    assert r.status == "open"
    filled = p.process_open_orders(NOW + timedelta(hours=1))
    assert filled[0].fill_price == 90 and p.positions()["T"].qty == 10


def test_resting_limit_expires(session_factory):
    p = PaperBroker(session_factory, quotes(95.0), initial_cash=10_000)
    p.place(rebuy("T", 10, limit=90, expires=NOW + timedelta(hours=1)), NOW)
    out = p.process_open_orders(NOW + timedelta(hours=2))
    assert out[0].status == "expired" and "T" not in p.positions()


def test_sell_records_realized_pnl(session_factory):
    p = PaperBroker(session_factory, quotes(100.0, 90.0), initial_cash=10_000, slippage_bps=0, commission_rate=0)
    p.place(buy("T", 10, key="b1"), NOW)
    p.place(OrderIntent(ticker="T", side="sell", qty=10, kind="sell", reason="x", idempotency_key="s1"), NOW)
    assert p.realized_pnls() == [pytest.approx(-100.0)]
