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
