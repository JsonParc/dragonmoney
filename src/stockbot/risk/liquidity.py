"""Absolute buy rules: never buy what we may not be able to sell."""
from __future__ import annotations

from stockbot.config import RiskConfig


def liquidity_ok(adv_usd: float, adv_shares: float, qty: int, cfg: RiskConfig) -> tuple[bool, str]:
    if adv_usd < cfg.min_adv_usd:
        return False, f"유동성 부족: 20일 평균 거래대금 ${adv_usd:,.0f} < ${cfg.min_adv_usd:,.0f}"
    if qty > cfg.max_adv_fraction * adv_shares:
        return False, f"유동성 부족: 주문 {qty}주 > 20일 평균 거래량의 {cfg.max_adv_fraction:.0%}"
    return True, ""


def affordable(price: float, budget_usd: float, cfg: RiskConfig) -> bool:
    return price <= budget_usd * cfg.max_position_pct
