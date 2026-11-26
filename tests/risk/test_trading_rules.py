from risk_helpers import buy, empty_pf, mkt

from stockbot.config import ModeState, RiskConfig, RuntimeConfig, TradingRules
from stockbot.data.universe import etf_info, load_etfs, sector_of
from stockbot.risk.liquidity import liquidity_ok
from stockbot.risk.rules import apply_risk, eligible


def test_active_rules_follow_broker_mode():
    c = RuntimeConfig()
    c.rules_paper.allow_etf = True
    assert c.active_rules().allow_etf is True
    c.mode.broker = "real"
    assert c.active_rules().allow_etf is False


def test_etf_catalog():
    assert etf_info("TQQQ").leverage == 3 and etf_info("SQQQ").leverage == -3 and etf_info("SPY").leverage == 1
    assert etf_info("AAPL") is None and len(load_etfs()) >= 40
    assert sector_of("XLE") == "Energy"


def test_eligibility():
    assert eligible("AAPL", TradingRules())[0]
    assert not eligible("SPY", TradingRules())[0]
    assert eligible("SPY", TradingRules(allow_etf=True))[0]
    ok, why = eligible("TQQQ", TradingRules(allow_etf=True))
    assert not ok and "레버리지" in why
    assert eligible("TQQQ", TradingRules(allow_etf=True, allow_leveraged_etf=True))[0]
    assert eligible("SOXL", TradingRules(allow_leveraged_etf=True))[0]  # independent of plain-ETF toggle
    assert eligible("SQQQ", TradingRules(allow_leveraged_etf=True))[0]  # inverse counts as leveraged product
    assert not eligible("SPY", TradingRules(allow_leveraged_etf=True))[0]


def test_low_volume_option_keeps_exit_cap():
    cfg = RiskConfig()
    assert liquidity_ok(10_000_000, 100_000, 10, cfg, allow_low_volume=True)[0]
    assert not liquidity_ok(10_000_000, 100_000, 10, cfg)[0]
    assert not liquidity_ok(10_000_000, 100_000, 1_001, cfg, allow_low_volume=True)[0]


def test_apply_risk_respects_rules():
    m = mkt(adv_usd={"TINY": 5e6}, adv_shares={"TINY": 1e5})
    args = (empty_pf(10_000), m, 10_000, RiskConfig(), ModeState(), False)
    assert apply_risk([buy("SPY", 1)], *args).accepted == []
    assert apply_risk([buy("SPY", 1)], *args, rules=TradingRules(allow_etf=True)).accepted
    assert apply_risk([buy("TINY", 5)], *args).accepted == []
    assert apply_risk([buy("TINY", 5)], *args, rules=TradingRules(allow_low_volume=True)).accepted
