import pytest
from helpers import make_df

from stockbot.signals.indicators import compute_indicators
from stockbot.signals.patterns import detect_patterns


def names(df):
    return {s.name for s in detect_patterns(df)}


def test_golden_cross_only_on_cross_day():
    cross_day = compute_indicators(make_df([100] * 30 + [101]))
    day_after = compute_indicators(make_df([100] * 30 + [101, 103]))
    flat = compute_indicators(make_df([100] * 30))
    assert "golden_cross_5_20" in names(cross_day)
    assert "golden_cross_5_20" not in names(day_after)
    assert "golden_cross_5_20" not in names(flat)


def test_dead_cross():
    df = compute_indicators(make_df([100] * 30 + [99]))
    assert "dead_cross_5_20" in names(df)


def test_volume_spike_text():
    df = compute_indicators(make_df([100] * 39 + [101], volumes=[1_000] * 39 + [4_100]))
    sig = next(s for s in detect_patterns(df) if s.name == "volume_spike")
    assert sig.strength == pytest.approx(4.1, rel=0.05) and "4.1배" in sig.text and sig.direction == "bull"


def test_aligned_bull_on_steady_uptrend():
    df = compute_indicators(make_df([100 + i for i in range(150)]))
    assert "aligned_bull" in names(df)
    assert df["rsi14"].iloc[-1] == pytest.approx(100)
    assert "rsi_overbought" in names(df)


def test_aligned_bear_on_downtrend():
    df = compute_indicators(make_df([300 - i for i in range(150)]))
    assert "aligned_bear" in names(df) and "rsi_oversold" in names(df)


def test_accumulation():
    closes = [100 + (i % 3) * 0.5 for i in range(100)]
    vols = [1_000] * 80 + [2_000] * 20
    df = compute_indicators(make_df(closes, vols))
    assert "accumulation" in names(df)


def test_box_breakout():
    closes = [100 + (i % 2) for i in range(40)] + [110]
    assert "box_breakout" in names(compute_indicators(make_df(closes)))


def test_long_bull_candle():
    closes = [100 + (i % 2) * 0.5 for i in range(40)] + [106]
    assert "long_bull_candle" in names(compute_indicators(make_df(closes)))


def test_flat_series_rsi_is_neutral():
    df = compute_indicators(make_df([100] * 40))
    assert df["rsi14"].iloc[-1] == pytest.approx(50) and names(df) == set()


def test_short_history_does_not_crash():
    assert isinstance(detect_patterns(compute_indicators(make_df([100, 101, 102]))), list)
