"""Company fundamentals (재무제표 지표) from free sources, cached for a day.

Live use only: these are *current* metrics. Backtests must not use them as-of a past date
(Plan 2 will use SEC filings with filing dates instead)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx
from pydantic import BaseModel

from stockbot.models import FundamentalsCache
from stockbot.orders_store import naive_utc

TTL = timedelta(hours=24)


class Fundamentals(BaseModel):
    ticker: str
    pe: float | None = None               # trailing P/E
    forward_pe: float | None = None
    ps: float | None = None               # price / sales
    pb: float | None = None               # price / book
    revenue_growth: float | None = None   # % YoY
    eps_growth: float | None = None       # % YoY
    gross_margin: float | None = None     # %
    operating_margin: float | None = None # %
    net_margin: float | None = None       # %
    roe: float | None = None              # %
    debt_to_equity: float | None = None   # ratio
    current_ratio: float | None = None
    dividend_yield: float | None = None   # %
    market_cap_musd: float | None = None  # millions USD
    source: str = ""


class FundamentalsSource(Protocol):
    def fetch(self, ticker: str) -> Fundamentals | None: ...


class FinnhubFundamentals:
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.key = api_key
        self.client = client or httpx.Client(timeout=20)

    def fetch(self, ticker: str) -> Fundamentals | None:
        r = self.client.get("https://finnhub.io/api/v1/stock/metric",
                            params={"symbol": ticker, "metric": "all", "token": self.key})
        r.raise_for_status()
        m = (r.json() or {}).get("metric") or {}
        if not m:
            return None
        g = m.get
        return Fundamentals(
            ticker=ticker, pe=g("peTTM") or g("peBasicExclExtraTTM"), forward_pe=g("forwardPE"), ps=g("psTTM"),
            pb=g("pbQuarterly") or g("pbAnnual"), revenue_growth=g("revenueGrowthTTMYoy"),
            eps_growth=g("epsGrowthTTMYoy"), gross_margin=g("grossMarginTTM"), operating_margin=g("operatingMarginTTM"),
            net_margin=g("netProfitMarginTTM"), roe=g("roeTTM"), debt_to_equity=g("totalDebt/totalEquityQuarterly"),
            current_ratio=g("currentRatioQuarterly"), dividend_yield=g("dividendYieldIndicatedAnnual"),
            market_cap_musd=g("marketCapitalization"), source="finnhub")


class YFinanceFundamentals:
    """PC fallback (Yahoo often blocks cloud servers)."""

    def fetch(self, ticker: str) -> Fundamentals | None:
        import yfinance as yf

        i = yf.Ticker(ticker).info or {}
        if not i.get("marketCap"):
            return None
        pct = lambda k: i[k] * 100 if i.get(k) is not None else None  # noqa: E731
        return Fundamentals(
            ticker=ticker, pe=i.get("trailingPE"), forward_pe=i.get("forwardPE"),
            ps=i.get("priceToSalesTrailing12Months"), pb=i.get("priceToBook"), revenue_growth=pct("revenueGrowth"),
            eps_growth=pct("earningsGrowth"), gross_margin=pct("grossMargins"), operating_margin=pct("operatingMargins"),
            net_margin=pct("profitMargins"), roe=pct("returnOnEquity"),
            debt_to_equity=(i["debtToEquity"] / 100 if i.get("debtToEquity") is not None else None),
            current_ratio=i.get("currentRatio"), dividend_yield=i.get("dividendYield"),
            market_cap_musd=i["marketCap"] / 1e6, source="yahoo")


class FundamentalsStore:
    def __init__(self, session_factory, sources: list[FundamentalsSource]):
        self._sf = session_factory
        self.sources = sources

    def get(self, ticker: str, now: datetime | None = None) -> Fundamentals | None:
        now = now or datetime.now(timezone.utc)
        with self._sf() as s:
            row = s.get(FundamentalsCache, ticker)
            if row and naive_utc(now) - row.fetched_at < TTL:
                return Fundamentals.model_validate_json(row.data) if row.data else None
        found = None
        for src in self.sources:
            try:
                found = src.fetch(ticker)
            except Exception:
                continue
            if found:
                break
        with self._sf() as s:
            row = s.get(FundamentalsCache, ticker) or FundamentalsCache(ticker=ticker)
            row.fetched_at, row.data = naive_utc(now), (found.model_dump_json() if found else "")
            s.merge(row)
            s.commit()
        return found


def _f(v: float | None, fmt: str) -> str | None:
    return None if v is None else fmt.format(v)


def digest(f: Fundamentals | None) -> list[str]:
    if f is None:
        return ["재무 데이터 없음"]
    lines = []
    if f.pe is not None:
        lines.append(f"PER {f.pe:.1f}배" + (f" (예상 {f.forward_pe:.1f}배)" if f.forward_pe else ""))
    for label, v, fmt in (("PSR", f.ps, "{:.1f}배"), ("PBR", f.pb, "{:.1f}배"),
                          ("매출 성장", f.revenue_growth, "{:+.1f}%"), ("EPS 성장", f.eps_growth, "{:+.1f}%"),
                          ("매출총이익률", f.gross_margin, "{:.1f}%"), ("영업이익률", f.operating_margin, "{:.1f}%"),
                          ("순이익률", f.net_margin, "{:.1f}%"), ("ROE", f.roe, "{:.1f}%"),
                          ("부채비율(D/E)", f.debt_to_equity, "{:.2f}"), ("유동비율", f.current_ratio, "{:.2f}"),
                          ("배당수익률", f.dividend_yield, "{:.2f}%")):
        s = _f(v, fmt)
        if s:
            lines.append(f"{label} {s}")
    if f.market_cap_musd:
        lines.append(f"시가총액 ${f.market_cap_musd / 1000:,.1f}B")
    lines.append(f"(출처: {f.source}, TTM·최근 분기 기준)")
    return lines


def to_json(f: Fundamentals | None) -> str:
    return json.dumps(f.model_dump() if f else None)
