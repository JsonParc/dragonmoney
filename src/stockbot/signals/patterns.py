"""Retail-style chart pattern rules ("차트쟁이"). Evaluated on the last row only."""
from __future__ import annotations

import math
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel


class ChartSignal(BaseModel):
    name: str
    direction: Literal["bull", "bear", "neutral"]
    strength: float
    text: str


def _ok(*vals) -> bool:
    return all(v is not None and not (isinstance(v, float) and math.isnan(v)) for v in vals)


def _cross(ind: pd.DataFrame, fast: str, slow: str) -> int:
    """+1 golden cross today, -1 dead cross today, 0 otherwise."""
    if len(ind) < 2:
        return 0
    f0, s0, f1, s1 = ind[fast].iloc[-2], ind[slow].iloc[-2], ind[fast].iloc[-1], ind[slow].iloc[-1]
    if not _ok(f0, s0, f1, s1):
        return 0
    if f0 <= s0 and f1 > s1:
        return 1
    if f0 >= s0 and f1 < s1:
        return -1
    return 0


def detect_patterns(ind: pd.DataFrame) -> list[ChartSignal]:
    if ind.empty:
        return []
    out: list[ChartSignal] = []
    last = ind.iloc[-1]
    o, h, l, c = (float(last[k]) for k in ("open", "high", "low", "close"))

    for fast, slow, label in (("ma5", "ma20", "5_20"), ("ma20", "ma60", "20_60")):
        x = _cross(ind, fast, slow)
        if x == 1:
            out.append(ChartSignal(name=f"golden_cross_{label}", direction="bull", strength=1.0,
                                   text=f"{fast[2:]}일선이 {slow[2:]}일선을 상향 돌파 (골든크로스)"))
        elif x == -1:
            out.append(ChartSignal(name=f"dead_cross_{label}", direction="bear", strength=1.0,
                                   text=f"{fast[2:]}일선이 {slow[2:]}일선을 하향 이탈 (데드크로스)"))

    m5, m20, m60, m120 = (last.get(k) for k in ("ma5", "ma20", "ma60", "ma120"))
    aligned_bull = _ok(m5, m20, m60, m120) and m5 > m20 > m60 > m120
    if aligned_bull:
        out.append(ChartSignal(name="aligned_bull", direction="bull", strength=1.0, text="이평선 정배열 (5>20>60>120)"))
    elif _ok(m5, m20, m60, m120) and m5 < m20 < m60 < m120:
        out.append(ChartSignal(name="aligned_bear", direction="bear", strength=1.0, text="이평선 역배열 (5<20<60<120)"))

    vr = last.get("vol_ratio20")
    if _ok(vr) and vr >= 3:
        d = "bull" if c > o else "bear" if c < o else "neutral"
        out.append(ChartSignal(name="volume_spike", direction=d, strength=float(vr),
                               text=f"거래량 20일 평균 대비 {vr:.1f}배"))

    if len(ind) >= 81:
        win = ind.iloc[-20:]
        rng = (win["high"].max() - win["low"].min()) / win["low"].min()
        v20 = win["volume"].mean()
        v60 = ind["volume"].iloc[-80:-20].mean()
        slope = np.polyfit(np.arange(20), win["obv"].to_numpy(), 1)[0]
        if rng <= 0.05 and v20 >= 1.5 * v60 and slope > 0:
            out.append(ChartSignal(name="accumulation", direction="bull", strength=float(v20 / v60),
                                   text=f"횡보 중 거래량 {v20 / v60:.1f}배 증가 + OBV 상승 (세력 매집 의심)"))

    if len(ind) >= 21:
        prev = ind.iloc[-21:-1]
        bodies = (prev["close"] - prev["open"]).abs()
        avg_body = float(bodies.mean())
        body = abs(c - o)
        if avg_body > 0 and body >= 2 * avg_body:
            name, d, word = ("long_bull_candle", "bull", "장대양봉") if c > o else ("long_bear_candle", "bear", "장대음봉")
            out.append(ChartSignal(name=name, direction=d, strength=body / avg_body,
                                   text=f"{word} (몸통이 20일 평균의 {body / avg_body:.1f}배)"))
        upper, lower = h - max(o, c), min(o, c) - l
        if body > 0 and upper >= 2 * body and upper >= 0.005 * c:
            out.append(ChartSignal(name="upper_wick", direction="bear", strength=upper / body, text="긴 윗꼬리 (매도 압력)"))
        if body > 0 and lower >= 2 * body and lower >= 0.005 * c:
            out.append(ChartSignal(name="lower_wick", direction="bull", strength=lower / body, text="긴 아랫꼬리 (매수 지지)"))

        box_hi, box_lo = float(prev["high"].max()), float(prev["low"].min())
        if (box_hi - box_lo) / box_lo <= 0.08:
            if c > box_hi:
                out.append(ChartSignal(name="box_breakout", direction="bull", strength=c / box_hi,
                                       text=f"20일 박스권 상단({box_hi:.2f}) 돌파"))
            elif c < box_lo:
                out.append(ChartSignal(name="box_breakdown", direction="bear", strength=box_lo / c,
                                       text=f"20일 박스권 하단({box_lo:.2f}) 이탈"))

    if aligned_bull and _ok(m20) and abs(c / m20 - 1) <= 0.02:
        out.append(ChartSignal(name="pullback_to_ma20", direction="bull", strength=1.0, text="정배열 중 20일선 눌림목"))

    rsi = last.get("rsi14")
    if _ok(rsi):
        if rsi >= 70:
            out.append(ChartSignal(name="rsi_overbought", direction="bear", strength=1.0, text=f"RSI {rsi:.0f} 과매수"))
        elif rsi <= 30:
            out.append(ChartSignal(name="rsi_oversold", direction="bull", strength=1.0, text=f"RSI {rsi:.0f} 과매도"))
    return out
