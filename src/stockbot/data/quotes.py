"""Live quote functions for the paper broker (spec §7.1: no yfinance on the server)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

import httpx

from stockbot.broker.base import Quote


def finnhub_quote_fn(api_key: str, client: httpx.Client | None = None) -> Callable[[str], Quote]:
    http = client or httpx.Client(timeout=15)

    def fn(ticker: str) -> Quote:
        r = http.get("https://finnhub.io/api/v1/quote", params={"symbol": ticker, "token": api_key})
        r.raise_for_status()
        d = r.json()
        ts = datetime.fromtimestamp(int(d.get("t") or 0), timezone.utc)
        return Quote(ticker=ticker, price=float(d.get("c") or 0.0), ts=ts, prev_close=float(d.get("pc") or 0.0))

    return fn


def yfinance_quote_fn() -> Callable[[str], Quote]:
    """PC fallback when no Finnhub key: last 1-minute bar from Yahoo."""

    def fn(ticker: str) -> Quote:
        import yfinance as yf

        t = yf.Ticker(ticker)
        hist = t.history(period="2d", interval="1m")
        daily = t.history(period="5d")
        if hist.empty:
            return Quote(ticker=ticker, price=0.0, ts=datetime.now(timezone.utc), prev_close=0.0)
        prev = float(daily["Close"].iloc[-2]) if len(daily) >= 2 else float(hist["Close"].iloc[0])
        return Quote(ticker=ticker, price=float(hist["Close"].iloc[-1]),
                     ts=hist.index[-1].to_pydatetime().astimezone(timezone.utc), prev_close=prev)

    return fn
