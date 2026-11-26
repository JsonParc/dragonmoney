"""Technical indicators computed with plain pandas."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.where(loss > 0, 100.0).where(gain.notna())
    return rsi.mask((gain == 0) & (loss == 0), 50.0)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c = out["close"]
    for n in (5, 20, 60, 120):
        out[f"ma{n}"] = c.rolling(n).mean()
    out["rsi14"] = _rsi(c)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    out["macd"] = ema12 - ema26
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    std20 = c.rolling(20).std()
    out["bb_upper"] = out["ma20"] + 2 * std20
    out["bb_lower"] = out["ma20"] - 2 * std20
    out["obv"] = (np.sign(c.diff()).fillna(0) * out["volume"]).cumsum()
    out["vol_ratio20"] = out["volume"] / out["volume"].shift(1).rolling(20).mean()
    return out
