"""Static settings (.env) and runtime settings (stored in DB, editable from web/telegram)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STOCKBOT_", env_file=".env", extra="ignore")

    db_url: str = "sqlite:///data/stockbot.db"
    data_dir: Path = Path("data")
    web_password: str
    pin: str
    secret_key: str
    telegram_token: str | None = None
    telegram_chat_ids: list[int] = []
    finnhub_key: str | None = None
    gemini_key: str | None = None
    groq_key: str | None = None
    openai_key: str | None = None
    anthropic_key: str | None = None
    # optional model id overrides (see llm/pricing.py DEFAULT_MODELS)
    gemini_model: str | None = None
    gemini_lite_model: str | None = None
    groq_model: str | None = None
    groq_alt_model: str | None = None
    groq_vision_model: str | None = None
    openai_model: str | None = None
    anthropic_model: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()


class RiskConfig(BaseModel):
    min_adv_usd: float = 50_000_000
    max_adv_fraction: float = 0.01
    max_position_pct: float = 0.20
    max_holdings: int = 8
    stop_loss_pct: float = -0.15
    circuit_breaker_dd: float = -0.20
    max_orders_per_day: int = 10
    max_daily_notional_pct: float = 0.30
    churn_round_trips: int = 3
    churn_window_days: int = 5
    max_consecutive_losses: int = 5
    quote_stale_minutes: int = 15
    quote_jump_pct: float = 0.25


class DebateConfig(BaseModel):
    seats_per_team: int = 3
    max_rebuttal_rounds: int = 2
    candidates_per_day: int = 5
    grading_horizon_days: int = 5
    neutral_threshold: float = 0.005
    hold_band: float = 0.02
    individual_point: float = 1.0
    bonus: float = 2.0
    persuasion_penalty: float = 2.0
    deadlock_penalty: float = 1.0
    invalid_penalty: float = 1.0
    weight_min: float = 0.5
    weight_max: float = 1.5
    weight_ema_alpha: float = 0.2
    weight_k: float = 0.5


class CostConfig(BaseModel):
    monthly_cap_usd: float = 10.0
    alert_ratio: float = 0.8


class ModeState(BaseModel):
    broker: Literal["paper", "real"] = "paper"
    automation: Literal["semi", "auto"] = "semi"
    paused: bool = False
    pause_reason: str | None = None


class SeatAssignment(BaseModel):
    seat_id: str
    providers: list[str]


class RuntimeConfig(BaseModel):
    risk: RiskConfig = Field(default_factory=RiskConfig)
    debate: DebateConfig = Field(default_factory=DebateConfig)
    cost: CostConfig = Field(default_factory=CostConfig)
    mode: ModeState = Field(default_factory=ModeState)
    seats: list[SeatAssignment] = []
    budget_usd: float = 10_000
    rebuy_auto: bool = True
    news_poll_minutes: int = 10
    severity_threshold: int = 4
    report_time_kst: str = "17:30"
