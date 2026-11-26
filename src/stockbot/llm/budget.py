from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import func, select

from stockbot.config import CostConfig
from stockbot.llm.base import LLMClient, LLMResponse
from stockbot.models import LLMSpend


def _month(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m") if now.tzinfo else now.strftime("%Y-%m")


class BudgetTracker:
    """Monthly cap on paid LLM spend. Free-tier calls are always allowed."""

    def __init__(self, session_factory, cfg: CostConfig):
        self._sf = session_factory
        self.cfg = cfg

    def month_spend(self, now: datetime) -> float:
        with self._sf() as s:
            v = s.execute(select(func.coalesce(func.sum(LLMSpend.cost_usd), 0.0))
                          .where(LLMSpend.month == _month(now))).scalar_one()
        return float(v)

    def allow(self, client: LLMClient, now: datetime) -> bool:
        return client.is_free or self.month_spend(now) < self.cfg.monthly_cap_usd

    def state(self, now: datetime) -> Literal["ok", "alert", "capped"]:
        spend = self.month_spend(now)
        if spend >= self.cfg.monthly_cap_usd:
            return "capped"
        if spend >= self.cfg.alert_ratio * self.cfg.monthly_cap_usd:
            return "alert"
        return "ok"

    def record(self, resp: LLMResponse, now: datetime) -> None:
        if resp.cost_usd <= 0:
            return
        with self._sf() as s:
            s.add(LLMSpend(month=_month(now), provider=resp.provider, model=resp.model, cost_usd=resp.cost_usd,
                           at=now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now))
            s.commit()
