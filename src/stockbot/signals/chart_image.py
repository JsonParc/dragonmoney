from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402


def render_chart_png(df: pd.DataFrame, path: Path, months: int = 6) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = df[["open", "high", "low", "close", "volume"]].copy()
    data.columns = ["Open", "High", "Low", "Close", "Volume"]
    full = data.copy()
    cutoff = data.index[-1] - pd.DateOffset(months=months)
    data = data[data.index >= cutoff]
    addplots = []
    for n, color in ((5, "#e4572e"), (20, "#f3a712"), (60, "#29335c"), (120, "#669bbc")):
        ma = full["Close"].rolling(n).mean().reindex(data.index)
        if ma.notna().any():
            addplots.append(mpf.make_addplot(ma, color=color, width=1))
    mpf.plot(data, type="candle", volume=True, style="yahoo", addplot=addplots or None,
             savefig=dict(fname=str(path), dpi=90), figsize=(8, 5))
    import matplotlib.pyplot as plt

    plt.close("all")
    return path
