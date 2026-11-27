"""All ORM tables. Each feature task appends its tables here."""
from __future__ import annotations

from datetime import date as _date
from datetime import datetime as _dt

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RuntimeSetting(Base):
    __tablename__ = "runtime_settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class Bar(Base):
    __tablename__ = "bars"
    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)


class PriceCoverage(Base):
    __tablename__ = "price_coverage"
    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    start: Mapped[_date] = mapped_column(Date)
    end: Mapped[_date] = mapped_column(Date)


class NewsRow(Base):
    __tablename__ = "news_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String, unique=True)
    title: Mapped[str] = mapped_column(Text)
    title_norm: Mapped[str] = mapped_column(Text, index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String)
    domain: Mapped[str | None] = mapped_column(String, index=True)
    wire: Mapped[str | None] = mapped_column(String)
    published_at: Mapped[_dt] = mapped_column(DateTime, index=True)
    fetched_at: Mapped[_dt] = mapped_column(DateTime)
    tickers: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    sentiment: Mapped[float] = mapped_column(Float, default=0.0)
    severity: Mapped[int] = mapped_column(Integer, default=0)
    cluster_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)


class NewsClusterRow(Base):
    __tablename__ = "news_clusters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    first_seen: Mapped[_dt] = mapped_column(DateTime)
    last_seen: Mapped[_dt] = mapped_column(DateTime, index=True)
    headline: Mapped[str] = mapped_column(Text)
    tickers: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    verification: Mapped[str] = mapped_column(String)
    independent_sources: Mapped[int] = mapped_column(Integer)
    best_tier: Mapped[int] = mapped_column(Integer)
    severity: Mapped[int] = mapped_column(Integer, default=0)


class LLMCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String, unique=True)
    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Float)
    response_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[_dt] = mapped_column(DateTime)


class LLMSpend(Base):
    __tablename__ = "llm_spend"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    month: Mapped[str] = mapped_column(String, index=True)
    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    cost_usd: Mapped[float] = mapped_column(Float)
    at: Mapped[_dt] = mapped_column(DateTime)


class DebateRow(Base):
    __tablename__ = "debates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    as_of: Mapped[_date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String)
    direction: Mapped[str | None] = mapped_column(String, nullable=True)
    deadlock: Mapped[bool] = mapped_column(Boolean)
    persuading_team: Mapped[str | None] = mapped_column(String, nullable=True)
    referee_summary: Mapped[str] = mapped_column(Text, default="")
    result_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[_dt] = mapped_column(DateTime)


class OpinionRow(Base):
    __tablename__ = "opinions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    debate_id: Mapped[int] = mapped_column(Integer, index=True)
    seat_id: Mapped[str] = mapped_column(String)
    team: Mapped[str] = mapped_column(String)
    round: Mapped[int] = mapped_column(Integer)
    valid: Mapped[bool] = mapped_column(Boolean)
    body_json: Mapped[dict] = mapped_column(JSON)


class DecisionRow(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    debate_id: Mapped[int] = mapped_column(Integer, index=True)
    ticker: Mapped[str] = mapped_column(String)
    as_of: Mapped[_date] = mapped_column(Date)
    direction: Mapped[str] = mapped_column(String)
    ref_price: Mapped[float] = mapped_column(Float)
    graded: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    ret: Mapped[float | None] = mapped_column(Float, nullable=True)
    persuading_team: Mapped[str | None] = mapped_column(String, nullable=True)
    seat_directions: Mapped[dict] = mapped_column(JSON, default=dict)
    seat_teams: Mapped[dict] = mapped_column(JSON, default=dict)


class SeatScore(Base):
    __tablename__ = "seat_scores"
    seat_id: Mapped[str] = mapped_column(String, primary_key=True)
    ema: Mapped[float] = mapped_column(Float, default=0.0)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    n: Mapped[int] = mapped_column(Integer, default=0)


class ScoreEvent(Base):
    __tablename__ = "score_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seat_id: Mapped[str] = mapped_column(String, index=True)
    debate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delta: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String)
    created_at: Mapped[_dt] = mapped_column(DateTime)


class OrderRow(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)
    qty: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    expires_at: Mapped[_dt | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, index=True)
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fill_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commission: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    needs_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    stage_expires_at: Mapped[_dt | None] = mapped_column(DateTime, nullable=True)
    guard_code: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[_dt] = mapped_column(DateTime)
    filled_at: Mapped[_dt | None] = mapped_column(DateTime, nullable=True)
    broker: Mapped[str] = mapped_column(String, default="")


class PaperPosition(Base):
    __tablename__ = "paper_positions"
    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    qty: Mapped[int] = mapped_column(Integer)
    avg_price: Mapped[float] = mapped_column(Float)


class PaperCash(Base):
    __tablename__ = "paper_cash"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cash: Mapped[float] = mapped_column(Float)
    peak_equity: Mapped[float] = mapped_column(Float)


class ApprovalRowDB(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String)
    expires_at: Mapped[_dt] = mapped_column(DateTime)
    decided_at: Mapped[_dt | None] = mapped_column(DateTime, nullable=True)


class HealthEvent(Base):
    __tablename__ = "health_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(String, index=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    detail: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[_dt] = mapped_column(DateTime)


class GuardEvent(Base):
    __tablename__ = "guard_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(Text)
    at: Mapped[_dt] = mapped_column(DateTime)
    cleared_at: Mapped[_dt | None] = mapped_column(DateTime, nullable=True)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    spy_close: Mapped[float | None] = mapped_column(Float, nullable=True)


class FundamentalsCache(Base):
    __tablename__ = "fundamentals_cache"
    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    fetched_at: Mapped[_dt] = mapped_column(DateTime)
    data: Mapped[str] = mapped_column(Text, default="")
