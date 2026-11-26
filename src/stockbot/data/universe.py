from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[3] / "data_static"


@dataclass(frozen=True)
class UniverseEntry:
    ticker: str
    name: str
    sector: str
    cik: str = ""


@lru_cache
def load_universe() -> list[UniverseEntry]:
    with open(_STATIC / "sp500.csv", encoding="utf-8") as f:
        return [UniverseEntry(r["ticker"], r["name"], r["sector"], r.get("cik", "")) for r in csv.DictReader(f)]


@dataclass(frozen=True)
class EtfEntry:
    ticker: str
    name: str
    category: str
    leverage: int  # 1 = plain, 2/3 = leveraged, negative = inverse

    @property
    def is_leveraged(self) -> bool:
        return self.leverage != 1


@lru_cache
def load_etfs() -> list[EtfEntry]:
    with open(_STATIC / "etfs.csv", encoding="utf-8") as f:
        return [EtfEntry(r["ticker"], r["name"], r["category"], int(r["leverage"])) for r in csv.DictReader(f)]


@lru_cache
def _etf_map() -> dict[str, EtfEntry]:
    return {e.ticker: e for e in load_etfs()}


def etf_info(ticker: str) -> EtfEntry | None:
    return _etf_map().get(ticker)


@lru_cache
def _sector_map() -> dict[str, str]:
    return {e.ticker: e.sector for e in load_universe()}


def sector_of(ticker: str) -> str:
    etf = etf_info(ticker)
    if etf:
        return etf.category
    return _sector_map().get(ticker, "")
