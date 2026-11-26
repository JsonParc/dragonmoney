from datetime import date

import pandas as pd
import pytest

from stockbot.data.prices import PriceStore, YFinanceFetcher
from stockbot.data.universe import load_universe


class FakeFetcher:
    def __init__(self):
        self.calls = 0

    def fetch(self, ticker, start, end):
        self.calls += 1
        idx = pd.bdate_range("2024-01-02", "2024-01-31")
        idx = idx[(idx.date >= start) & (idx.date <= end)]
        return pd.DataFrame(
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 600_000},
            index=idx,
        )


@pytest.fixture
def fake_fetcher():
    return FakeFetcher()


@pytest.fixture
def store(session_factory, fake_fetcher):
    s = PriceStore(session_factory, fake_fetcher)
    s.ensure(["AAPL"], date(2024, 1, 2), date(2024, 1, 31))
    return s


def test_as_of_excludes_future(store):
    df = store.get_bars("AAPL", as_of=date(2024, 1, 10), lookback=5)
    assert df.index[-1].date() == date(2024, 1, 10) and len(df) == 5


def test_cache_hit_does_not_refetch(store, fake_fetcher):
    store.get_bars("AAPL", date(2024, 1, 10), 5)
    store.get_bars("AAPL", date(2024, 1, 9), 3)
    assert fake_fetcher.calls == 1


def test_adv_usd(store):
    assert store.adv_usd("AAPL", date(2024, 1, 31)) == pytest.approx(60_000_000)
    assert store.adv_shares("AAPL", date(2024, 1, 31)) == pytest.approx(600_000)


def test_close_on(store):
    assert store.close_on("AAPL", date(2024, 1, 6)) == 100.0  # Saturday -> Friday close


def test_universe_has_sectors():
    u = load_universe()
    assert len(u) >= 490 and all(e.sector for e in u)


@pytest.mark.network
def test_yfinance_spy():
    df = YFinanceFetcher().fetch("SPY", date(2024, 1, 2), date(2024, 1, 9))
    assert len(df) == 6 and {"open", "high", "low", "close", "volume"} <= set(df.columns)
