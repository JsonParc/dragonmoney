from datetime import date

import pandas as pd
import pytest
from helpers import make_df

from stockbot.config import RiskConfig, RuntimeConfig
from stockbot.data.prices import PriceStore
from stockbot.risk.liquidity import affordable, liquidity_ok
from stockbot.risk.portfolio import PositionView
from stockbot.signals.chart_image import render_chart_png
from stockbot.signals.screener import screen

AS_OF = date(2024, 6, 3)


def _series(base, last, n=40, vol=600_000, last_vol=None):
    df = make_df([base] * (n - 1) + [last], [vol] * (n - 1) + [last_vol or vol])
    df.index = pd.bdate_range(end=pd.Timestamp(AS_OF), periods=n)
    return df


class MultiFetcher:
    def __init__(self, frames):
        self.frames = frames

    def fetch(self, ticker, start, end):
        return self.frames[ticker]


@pytest.fixture
def fake_prices(session_factory):
    frames = {f"UP{k}": _series(100, 101, last_vol=600_000 * k) for k in range(3, 9)}
    frames["ILLIQ"] = _series(100, 101, vol=200_000, last_vol=200_000 * 9)  # ADV ~ $28M
    frames["PRICEY"] = _series(5_000, 5_050, last_vol=600_000 * 9)
    frames["CALM"] = _series(100, 100)
    frames["DROP"] = _series(100, 96)
    store = PriceStore(session_factory, MultiFetcher(frames))
    store.ensure(list(frames), date(2024, 1, 1), AS_OF)
    store.tickers = [t for t in frames if t not in ("CALM", "DROP")]
    return store


def pos(t, avg=100.0, last=100.0, qty=10):
    return PositionView(ticker=t, qty=qty, avg_price=avg, last_price=last)


def test_liquidity_threshold():
    cfg = RiskConfig()
    assert not liquidity_ok(49_000_000, 1e6, 10, cfg)[0]
    assert liquidity_ok(51_000_000, 1e6, 10, cfg)[0]
    assert not liquidity_ok(51_000_000, 1_000, 11, cfg)[0]  # 11 > 1% of 1,000


def test_affordable():
    assert affordable(1_999, 10_000, RiskConfig()) and not affordable(2_001, 10_000, RiskConfig())


def test_screen_limits_and_filters(fake_prices):
    out = screen(AS_OF, fake_prices.tickers, {}, fake_prices, {}, 10_000, RuntimeConfig())
    tickers = {c.ticker for c in out}
    assert len(out) == 5 and "ILLIQ" not in tickers and "PRICEY" not in tickers
    assert [c.score for c in out] == sorted([c.score for c in out], reverse=True)
    assert "UP3" not in tickers  # weakest of six bull candidates is cut


def test_screen_includes_flagged_holdings_only(fake_prices):
    held = {"CALM": pos("CALM"), "DROP": pos("DROP", last=96.0)}
    out = screen(AS_OF, [], held, fake_prices, {}, 10_000, RuntimeConfig())
    assert {c.ticker for c in out} == {"DROP"} and out[0].held


def test_screen_flags_holding_on_news_or_stop(fake_prices):
    held = {"CALM": pos("CALM")}
    assert screen(AS_OF, [], held, fake_prices, {"CALM": 3}, 10_000, RuntimeConfig())[0].ticker == "CALM"
    near_stop = {"CALM": pos("CALM", avg=115.0, last=100.0)}  # -13%, within 3%p of -15%
    assert screen(AS_OF, [], near_stop, fake_prices, {}, 10_000, RuntimeConfig())[0].held


def test_render_chart_png(tmp_path):
    df = make_df([100 + (i % 7) for i in range(130)])
    p = render_chart_png(df, tmp_path / "c.png")
    assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
