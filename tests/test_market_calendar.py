from datetime import date, datetime

from stockbot.market_calendar import (
    KST,
    is_market_open,
    is_trading_day,
    next_trading_day,
    trading_days_between,
    trading_session,
)


def test_winter_session():
    s = trading_session(date(2026, 12, 1))
    assert s.open_kst == datetime(2026, 12, 1, 23, 30, tzinfo=KST)
    assert s.close_kst == datetime(2026, 12, 2, 6, 0, tzinfo=KST)


def test_summer_session():
    s = trading_session(date(2026, 7, 1))
    assert s.open_kst == datetime(2026, 7, 1, 22, 30, tzinfo=KST)
    assert s.close_kst == datetime(2026, 7, 2, 5, 0, tzinfo=KST)


def test_holiday_and_early_close():
    assert not is_trading_day(date(2025, 12, 25))
    assert not is_trading_day(date(2026, 11, 26))  # Thanksgiving
    assert trading_session(date(2026, 11, 27)).close_kst == datetime(2026, 11, 28, 3, 0, tzinfo=KST)
    assert next_trading_day(date(2026, 12, 24)) == date(2026, 12, 28)


def test_trading_days_between():
    assert trading_days_between(date(2026, 12, 21), date(2026, 12, 28)) == 4  # 22,23,24,28


def test_is_market_open():
    assert is_market_open(datetime(2026, 12, 2, 0, 0, tzinfo=KST))
    assert not is_market_open(datetime(2026, 12, 2, 7, 0, tzinfo=KST))
