from risk_helpers import D, buy, empty_pf, mkt, pf_with, pf_with_n_holdings, res, sell

from stockbot.config import ModeState, RiskConfig
from stockbot.risk.portfolio import PortfolioView
from stockbot.risk.rules import apply_risk, circuit_breaker_tripped, decision_to_intents, forced_stop_losses


def test_buy_sizing_clipped():
    ints = decision_to_intents(res("BUY", size_pct=0.3), 7, empty_pf(cash=10_000), mkt(price=150), 10_000, RiskConfig(), D)
    assert ints[0].qty == 13 and ints[0].kind == "new_buy" and ints[0].idempotency_key == "7:new_buy:T"


def test_add_counts_existing_position():
    pf = pf_with("T", qty=10, avg=100, last=100)
    ints = decision_to_intents(res("ADD", size_pct=0.2), 3, pf, mkt(100), 10_000, RiskConfig(), D)
    assert ints[0].kind == "add" and ints[0].qty == 10  # 2,000 target - 1,000 held


def test_hold_makes_no_orders():
    assert decision_to_intents(res("HOLD"), 1, empty_pf(), mkt(), 10_000, RiskConfig(), D) == []


def test_trim_default_half():
    ints = decision_to_intents(res("TRIM"), 2, pf_with("T", 9, 100, 100), mkt(), 10_000, RiskConfig(), D)
    assert [(i.side, i.kind, i.qty) for i in ints] == [("sell", "trim", 4)]


def test_sell_rebuy_creates_two_orders():
    ints = decision_to_intents(res("SELL_REBUY", rebuy_price=90), 8, pf_with("T", qty=10, avg=100, last=98), mkt(98),
                               10_000, RiskConfig(), D)
    assert [(i.side, i.kind, i.qty) for i in ints] == [("sell", "sell", 10), ("buy", "rebuy", 10)]
    assert ints[1].limit_price == 90 and ints[1].expires_at is not None


def test_switch_sells_and_buys_target():
    ints = decision_to_intents(res("SWITCH", switch_to="XOM"), 9, pf_with("T", 10, 100, 100), mkt(prices={"XOM": 50}),
                               10_000, RiskConfig(), D)
    assert [(i.ticker, i.kind) for i in ints] == [("T", "switch_sell"), ("XOM", "switch_buy")] and ints[1].qty == 20


def test_liquidity_and_holdings_rejections():
    out = apply_risk([buy("ILLIQ", 5)], empty_pf(10_000), mkt(adv_usd={"ILLIQ": 49e6}), 10_000, RiskConfig(), ModeState(), False)
    assert out.accepted == [] and "유동성" in out.rejected[0][1]
    out = apply_risk([buy("NEW", 1)], pf_with_n_holdings(8), mkt(), 10_000, RiskConfig(), ModeState(), False)
    assert out.accepted == []


def test_buy_clipped_to_budget_and_cash():
    out = apply_risk([buy("A", 50)], empty_pf(cash=1_000), mkt(100), 10_000, RiskConfig(), ModeState(), False)
    assert out.accepted[0].qty == 10


def test_unaffordable_rejected():
    out = apply_risk([buy("BIG", 1)], empty_pf(), mkt(prices={"BIG": 5_000}), 10_000, RiskConfig(), ModeState(), False)
    assert out.accepted == []


def test_paused_blocks_buys_not_sells():
    out = apply_risk([buy("A", 1), sell("B", 1)], pf_with("B", 1, 100, 100), mkt(), 10_000, RiskConfig(),
                     ModeState(paused=True), False)
    assert [i.side for i in out.accepted] == ["sell"]


def test_circuit_blocks_buys():
    out = apply_risk([buy("A", 1)], empty_pf(), mkt(), 10_000, RiskConfig(), ModeState(), True)
    assert out.accepted == [] and "서킷" in out.rejected[0][1]


def test_sell_more_than_held_is_clipped():
    out = apply_risk([sell("B", 5)], pf_with("B", 2, 100, 100), mkt(), 10_000, RiskConfig(), ModeState(), False)
    assert out.accepted[0].qty == 2


def test_forced_stop_loss_boundary():
    assert forced_stop_losses(pf_with("T", 10, 100, 84.9), RiskConfig(), D)[0].kind == "stop_loss"
    assert forced_stop_losses(pf_with("T", 10, 100, 85.1), RiskConfig(), D) == []


def test_circuit_breaker():
    assert circuit_breaker_tripped(PortfolioView(cash=7_999, positions={}, peak_equity=10_000), RiskConfig())
    assert not circuit_breaker_tripped(PortfolioView(cash=8_001, positions={}, peak_equity=10_000), RiskConfig())
