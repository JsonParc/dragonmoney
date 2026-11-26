from datetime import datetime, timedelta

from risk_helpers import D, buy, round_trips

from stockbot.config import RiskConfig
from stockbot.market_calendar import KST
from stockbot.risk.guards import check_churn, check_consecutive_losses, check_daily_limits, check_ledger, check_quote

NOW = datetime(2026, 12, 2, 8, 0, tzinfo=KST)              # market closed
NOW_MARKET_OPEN = datetime(2026, 12, 2, 1, 0, tzinfo=KST)  # NYSE session of 12/1


def test_bad_quote_guards():
    assert check_quote(0, NOW, NOW, 100).code == "BAD_QUOTE"
    assert check_quote(130, NOW, NOW, 100).code == "BAD_QUOTE"
    assert check_quote(101, NOW_MARKET_OPEN - timedelta(minutes=20), NOW_MARKET_OPEN, 100).code == "DATA_STALE"
    assert check_quote(101, NOW - timedelta(hours=5), NOW, 100) is None  # stale is fine while closed
    assert check_quote(101, NOW, NOW, 100) is None


def test_churn_and_limits():
    assert check_churn(round_trips("T", n=3, within_days=4), D, RiskConfig()).code == "CHURN"
    assert check_churn(round_trips("T", n=2, within_days=4), D, RiskConfig()) is None
    assert check_daily_limits([buy(f"T{i}", 1) for i in range(11)], {}, 10_000, RiskConfig()).code == "DAILY_ORDER_LIMIT"
    assert check_daily_limits([buy("A", 40)], {"A": 100}, 10_000, RiskConfig()).code == "DAILY_ORDER_LIMIT"
    assert check_daily_limits([buy("A", 20)], {"A": 100}, 10_000, RiskConfig()) is None
    assert check_consecutive_losses([-1] * 5, RiskConfig()).code == "CONSECUTIVE_LOSSES"
    assert check_consecutive_losses([-1, -1, 2, -1, -1, -1, -1], RiskConfig()) is None
    assert check_ledger({"A": 10}, {"A": 9}).code == "LEDGER_MISMATCH"
    assert check_ledger({"A": 10}, {"A": 10}) is None
