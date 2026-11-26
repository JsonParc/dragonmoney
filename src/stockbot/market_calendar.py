"""NYSE trading calendar expressed in KST (the user's clock)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

KST = ZoneInfo("Asia/Seoul")
NY = ZoneInfo("America/New_York")

_CAL = xcals.get_calendar(
    "XNYS",
    start=pd.Timestamp("2005-01-03"),
    end=pd.Timestamp(date.today() + timedelta(days=730)),
)


@dataclass(frozen=True)
class Session:
    date: date
    open_kst: datetime
    close_kst: datetime


def is_trading_day(d: date) -> bool:
    return bool(_CAL.is_session(pd.Timestamp(d)))


def trading_session(d: date) -> Session:
    if not is_trading_day(d):
        raise ValueError(f"{d} is not a NYSE trading day")
    ts = pd.Timestamp(d)
    return Session(
        date=d,
        open_kst=_CAL.session_open(ts).to_pydatetime().astimezone(KST),
        close_kst=_CAL.session_close(ts).to_pydatetime().astimezone(KST),
    )


def next_trading_day(d: date) -> date:
    return _CAL.date_to_session(pd.Timestamp(d + timedelta(days=1)), direction="next").date()


def previous_trading_day(d: date) -> date:
    return _CAL.date_to_session(pd.Timestamp(d - timedelta(days=1)), direction="previous").date()


def trading_days_between(start: date, end: date) -> int:
    """Number of sessions in (start, end]."""
    if end <= start:
        return 0
    return len(_CAL.sessions_in_range(pd.Timestamp(start + timedelta(days=1)), pd.Timestamp(end)))


def add_trading_days(d: date, n: int) -> date:
    out = d
    for _ in range(n):
        out = next_trading_day(out)
    return out


def is_market_open(now: datetime) -> bool:
    return bool(_CAL.is_open_on_minute(pd.Timestamp(now).tz_convert("UTC").floor("min")))
