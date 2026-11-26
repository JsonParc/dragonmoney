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
