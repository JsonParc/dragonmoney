"""Daily bars cached in SQLite. Reads are always as-of; only ensure() touches the network."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Protocol

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from stockbot.models import Bar, PriceCoverage

MACRO_TICKERS = {
    "oil": "CL=F",
    "us10y": "^TNX",
    "dxy": "DX-Y.NYB",
    "vix": "^VIX",
    "gold": "GC=F",
    "usdkrw": "KRW=X",
    "spy": "SPY",
    "qqq": "QQQ",
}

SECTOR_ETFS = {
    "Information Technology": "XLK",
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
}

_COLS = ["open", "high", "low", "close", "volume"]


class BarFetcher(Protocol):
    def fetch(self, ticker: str, start: date, end: date) -> pd.DataFrame: ...


class YFinanceFetcher:
    def fetch(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        import yfinance as yf

        df = yf.Ticker(ticker).history(
            start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(), auto_adjust=True
        )
        if df.empty:
            return pd.DataFrame(columns=_COLS)
        df = df.rename(columns=str.lower)[_COLS]
        df.index = pd.DatetimeIndex([ts.date() for ts in df.index])
        return df


class PriceStore:
    def __init__(self, session_factory, fetcher: BarFetcher):
        self._sf = session_factory
        self._fetcher = fetcher

    # ---- network ---------------------------------------------------------
    def ensure(self, tickers: list[str], start: date, end: date) -> None:
        cap = date.today() - timedelta(days=1)
        cover_end = min(end, cap) if end >= date.today() else end
        for t in tickers:
            with self._sf() as s:
                cov = s.get(PriceCoverage, t)
                ranges = []
                if cov is None:
                    ranges.append((start, end))
                else:
                    if start < cov.start:
                        ranges.append((start, cov.start - timedelta(days=1)))
                    if end > cov.end:
                        ranges.append((cov.end + timedelta(days=1), end))
                for a, b in ranges:
                    self._store(s, t, self._fetcher.fetch(t, a, b))
                if ranges:
                    if cov is None:
                        s.add(PriceCoverage(ticker=t, start=start, end=cover_end))
                    else:
                        cov.start = min(cov.start, start)
                        cov.end = max(cov.end, cover_end)
                s.commit()

    @staticmethod
    def _store(s, ticker: str, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        rows = [
            {"ticker": ticker, "date": pd.Timestamp(ix).date(), **{c: float(r[c]) for c in _COLS}}
            for ix, r in df.iterrows()
        ]
        stmt = insert(Bar).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "date"], set_={c: stmt.excluded[c] for c in _COLS}
        )
        s.execute(stmt)

    # ---- as-of reads -----------------------------------------------------
    def get_bars(self, ticker: str, as_of: date, lookback: int) -> pd.DataFrame:
        with self._sf() as s:
            rows = s.execute(
                select(Bar).where(Bar.ticker == ticker, Bar.date <= as_of).order_by(Bar.date.desc()).limit(lookback)
            ).scalars().all()
        rows = list(reversed(rows))
        df = pd.DataFrame([{c: getattr(r, c) for c in _COLS} for r in rows], columns=_COLS)
        df.index = pd.DatetimeIndex([pd.Timestamp(r.date) for r in rows])
        return df

    def close_on(self, ticker: str, d: date) -> float:
        df = self.get_bars(ticker, d, 1)
        if df.empty:
            raise KeyError(f"no bars for {ticker} on/before {d}")
        return float(df["close"].iloc[-1])

    def adv_usd(self, ticker: str, as_of: date, window: int = 20) -> float:
        df = self.get_bars(ticker, as_of, window)
        return float((df["close"] * df["volume"]).mean()) if not df.empty else 0.0

    def adv_shares(self, ticker: str, as_of: date, window: int = 20) -> float:
        df = self.get_bars(ticker, as_of, window)
        return float(df["volume"].mean()) if not df.empty else 0.0
