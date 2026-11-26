"""First-pass filter: decide which tickers are worth an (expensive) LLM debate today."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from stockbot.config import RuntimeConfig
from stockbot.data.prices import PriceStore
from stockbot.risk.liquidity import affordable, liquidity_ok
from stockbot.risk.portfolio import PositionView
from stockbot.signals.indicators import compute_indicators
from stockbot.signals.patterns import ChartSignal, detect_patterns

LOOKBACK = 260
FLAG_DAILY_MOVE = 0.03
FLAG_STOP_MARGIN = 0.03
FLAG_NEWS_SEVERITY = 3


class Candidate(BaseModel):
    ticker: str
    score: float
    signals: list[ChartSignal]
    reason: str
    held: bool


def _score(signals: list[ChartSignal]) -> float:
    return sum(s.strength for s in signals if s.direction == "bull") - sum(
        s.strength for s in signals if s.direction == "bear"
    )


def _signals(prices: PriceStore, ticker: str, as_of: date):
    df = prices.get_bars(ticker, as_of, LOOKBACK)
    if len(df) < 2:
        return df, []
    return df, detect_patterns(compute_indicators(df))


def screen(
    as_of: date,
    universe: list[str],
    held: dict[str, PositionView],
    prices: PriceStore,
    news_severity: dict[str, int],
    budget_usd: float,
    cfg: RuntimeConfig,
) -> list[Candidate]:
    out: list[Candidate] = []

    for t, p in held.items():
        df, sigs = _signals(prices, t, as_of)
        reasons = []
        if len(df) >= 2:
            move = df["close"].iloc[-1] / df["close"].iloc[-2] - 1
            if abs(move) >= FLAG_DAILY_MOVE:
                reasons.append(f"당일 {move:+.1%}")
        if p.pnl_pct <= cfg.risk.stop_loss_pct + FLAG_STOP_MARGIN:
            reasons.append(f"손절선 근접 ({p.pnl_pct:+.1%})")
        if news_severity.get(t, 0) >= FLAG_NEWS_SEVERITY:
            reasons.append(f"뉴스 심각도 {news_severity[t]}")
        if any(s.direction == "bear" for s in sigs):
            reasons.append("약세 차트 신호")
        if reasons:
            out.append(Candidate(ticker=t, score=_score(sigs), signals=sigs, reason=", ".join(reasons), held=True))

    fresh: list[Candidate] = []
    for t in universe:
        if t in held:
            continue
        df, sigs = _signals(prices, t, as_of)
        if df.empty:
            continue
        price = float(df["close"].iloc[-1])
        if not affordable(price, budget_usd, cfg.risk):
            continue
        est_qty = int(budget_usd * cfg.risk.max_position_pct // price)
        ok, _ = liquidity_ok(prices.adv_usd(t, as_of), prices.adv_shares(t, as_of), est_qty, cfg.risk)
        if not ok:
            continue
        score = _score(sigs)
        if score <= 0:
            continue
        fresh.append(Candidate(ticker=t, score=score, signals=sigs,
                               reason=", ".join(s.text for s in sigs if s.direction == "bull"), held=False))
    fresh.sort(key=lambda c: c.score, reverse=True)
    return out + fresh[: cfg.debate.candidates_per_day]
