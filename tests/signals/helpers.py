import pandas as pd


def make_df(closes, volumes=None):
    n = len(closes)
    volumes = volumes or [1_000] * n
    opens = [closes[0]] + list(closes[:-1])
    highs = [max(o, c) * 1.001 for o, c in zip(opens, closes)]
    lows = [min(o, c) * 0.999 for o, c in zip(opens, closes)]
    idx = pd.bdate_range("2023-01-02", periods=n)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}, index=idx
    ).astype(float)
