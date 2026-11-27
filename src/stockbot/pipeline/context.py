"""Build the evidence pack each debate sees, plus portfolio/market views for risk rules."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from stockbot.data.prices import MACRO_TICKERS
from stockbot.data.universe import etf_info, sector_of
from stockbot.data.verify import digest_line
from stockbot.debate.engine import DebateContext
from stockbot.market_calendar import is_trading_day, previous_trading_day, trading_session
from stockbot.risk.portfolio import PortfolioView, PositionView
from stockbot.sentiment.impact import TAG_SECTOR_IMPACT
from stockbot.signals.chart_image import render_chart_png
from stockbot.signals.indicators import compute_indicators
from stockbot.signals.patterns import detect_patterns

MACRO_LABELS = {"oil": "유가(WTI)", "us10y": "미 10년물 금리", "vix": "VIX", "dxy": "달러인덱스", "spy": "S&P500(SPY)"}


def session_end(d: date) -> datetime:
    day = d if is_trading_day(d) else previous_trading_day(d)
    return trading_session(day).close_kst


class PriceMarket:
    """MarketView backed by stored closes (used at post-close)."""

    def __init__(self, prices, as_of: date):
        self.prices, self.as_of = prices, as_of

    def last_price(self, t: str) -> float:
        try:
            return self.prices.close_on(t, self.as_of)
        except KeyError:
            return 0.0

    def adv_usd(self, t: str) -> float:
        return self.prices.adv_usd(t, self.as_of)

    def adv_shares(self, t: str) -> float:
        return self.prices.adv_shares(t, self.as_of)


def portfolio_view(deps, mkt) -> PortfolioView:
    pos = {}
    for t, p in deps.broker.positions().items():
        last = mkt.last_price(t) or p.avg_price
        pos[t] = PositionView(ticker=t, qty=p.qty, avg_price=p.avg_price, last_price=last)
    cash = deps.broker.cash()
    equity = cash + sum(p.value for p in pos.values())
    peak = deps.broker.update_peak(equity) if hasattr(deps.broker, "update_peak") else equity
    return PortfolioView(cash=cash, positions=pos, peak_equity=peak)


def relevant_clusters(deps, ticker: str, sector: str, as_of: datetime, hours: int = 72):
    out = []
    for c in deps.verifier.recent(as_of, hours):
        if ticker in c.tickers or any(TAG_SECTOR_IMPACT.get(t, {}).get(sector, 0) for t in c.tags):
            out.append(c)
    return out


def macro_digest(deps, as_of: date) -> list[str]:
    lines = []
    for key, label in MACRO_LABELS.items():
        df = deps.prices.get_bars(MACRO_TICKERS[key], as_of, 6)
        if len(df) >= 2:
            ch = df["close"].iloc[-1] / df["close"].iloc[0] - 1
            lines.append(f"{label}: {df['close'].iloc[-1]:.2f} (5일 {ch:+.1%})")
    return lines


def _fundamentals(deps, ticker: str, etf) -> list[str]:
    from stockbot.data.fundamentals import digest

    if etf is not None:
        return ["ETF라 재무제표가 없음 — 구성 종목·섹터·운용 방식(레버리지 등)으로 판단할 것"]
    store = getattr(deps, "fundamentals", None)
    if store is None:
        return ["재무 데이터 소스 미설정"]
    try:
        return digest(store.get(ticker))
    except Exception:
        return ["재무 데이터 조회 실패"]


def build_context(deps, ticker: str, as_of: date, kind: str, holding: PositionView | None,
                  news_as_of: datetime | None = None) -> DebateContext:
    sector = sector_of(ticker)
    bars = deps.prices.get_bars(ticker, as_of, 260)
    ind = compute_indicators(bars) if len(bars) >= 2 else bars
    sigs = detect_patterns(ind) if len(bars) >= 2 else []
    last = ind.iloc[-1] if len(ind) else None
    summary: dict[str, float] = {}
    if last is not None:
        for k in ("rsi14", "macd", "vol_ratio20"):
            v = last.get(k)
            if v is not None and v == v:
                summary[k] = float(v)
        if last.get("ma20") == last.get("ma20") and last.get("ma20"):
            summary["close_vs_ma20"] = float(last["close"] / last["ma20"] - 1)
    png = None
    if deps.render_charts and len(bars) >= 30:
        try:
            png = render_chart_png(bars, deps.chart_dir / f"{ticker}_{as_of.isoformat()}.png").read_bytes()
        except Exception:
            png = None
    at = news_as_of or session_end(as_of)
    clusters = relevant_clusters(deps, ticker, sector, at)
    news_lines = [digest_line(c) for c in clusters if c.verification != "contradicted"][:8]
    news_lines += [f"반박된 루머: {c.headline}" for c in clusters if c.verification == "contradicted"][:3]
    price = float(bars["close"].iloc[-1]) if len(bars) else (holding.last_price if holding else 0.0)
    etf = etf_info(ticker)
    note = None
    if etf:
        note = (f"{etf.name} ({'인버스 ' if etf.leverage < 0 else ''}{abs(etf.leverage)}배 레버리지 ETF)"
                if etf.is_leveraged else f"{etf.name} (ETF, {etf.category})")
    return DebateContext(ticker=ticker, sector=sector, as_of=as_of, kind=kind, holding=holding, last_price=price,
                         chart_signals=[s.text for s in sigs], indicator_summary=summary, chart_png=png,
                         news_digest=news_lines, macro_digest=macro_digest(deps, as_of),
                         scoreboard_text=deps.scoreboard.summary_text(), product_note=note,
                         fundamentals_digest=_fundamentals(deps, ticker, etf))


def utc(ts: datetime) -> datetime:
    return ts.astimezone(timezone.utc)


def next_open_after(now: datetime) -> datetime:
    d = now.date() - timedelta(days=1)
    for _ in range(10):
        if is_trading_day(d):
            o = trading_session(d).open_kst
            if o > now:
                return o
        d += timedelta(days=1)
    raise RuntimeError("no upcoming session found")
