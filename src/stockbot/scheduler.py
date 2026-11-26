"""KST schedule derived from the NYSE calendar (handles DST, holidays, early closes)."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from pydantic import BaseModel

from stockbot.config import RuntimeConfig
from stockbot.market_calendar import KST, is_market_open, is_trading_day, next_trading_day, previous_trading_day, trading_session

log = logging.getLogger(__name__)
JobName = Literal["post_close", "report", "pre_open", "open", "open_retry"]
OPEN_DELAYS = (5, 20, 45)  # minutes after the bell: first quotes of the day are often still yesterday's


class ScheduledJob(BaseModel):
    name: JobName
    run_at: datetime
    session_date: date
    final: bool = False


def plan_jobs(kst_day: date, cfg: RuntimeConfig) -> list[ScheduledJob]:
    jobs: list[ScheduledJob] = []
    for k in (2, 1, 0):
        d = kst_day - timedelta(days=k)
        if not is_trading_day(d):
            continue
        s = trading_session(d)
        pc = s.close_kst + timedelta(minutes=30)
        if pc.date() == kst_day:
            jobs.append(ScheduledJob(name="post_close", run_at=pc, session_date=d))
    if is_trading_day(kst_day):
        s = trading_session(kst_day)
        if s.open_kst.date() == kst_day:
            last = previous_trading_day(kst_day)
            hh, mm = (int(x) for x in cfg.report_time_kst.split(":"))
            jobs.append(ScheduledJob(name="report", run_at=datetime.combine(kst_day, time(hh, mm), KST), session_date=last))
            jobs.append(ScheduledJob(name="pre_open", run_at=s.open_kst - timedelta(minutes=30), session_date=kst_day))
            for k, mins in enumerate(OPEN_DELAYS):
                jobs.append(ScheduledJob(name="open" if k == 0 else "open_retry", run_at=s.open_kst + timedelta(minutes=mins),
                                         session_date=kst_day, final=k == len(OPEN_DELAYS) - 1))
    return sorted(jobs, key=lambda j: j.run_at)


def catch_up(deps, cycle, now: datetime) -> list[tuple[str, date]]:
    """Run jobs missed while the PC was asleep / the process was down."""
    ran: list[tuple[str, date]] = []
    today = now.astimezone(KST).date()
    latest = None
    for k in range(7):
        d = today - timedelta(days=k)
        if is_trading_day(d) and trading_session(d).close_kst + timedelta(minutes=30) <= now:
            latest = d
            break
    if latest and not cycle.done("post_close", latest):
        if now < trading_session(next_trading_day(latest)).open_kst:
            cycle.post_close(latest, now)
            ran.append(("post_close", latest))
    if is_market_open(now):
        for k in (0, 1):
            d = today - timedelta(days=k)
            if is_trading_day(d) and trading_session(d).open_kst <= now <= trading_session(d).close_kst:
                if not cycle.done("open", d):
                    cycle.at_open(d, now)
                    ran.append(("open", d))
                break
    return ran


def start_scheduler(deps, cycle, watcher):
    from apscheduler.schedulers.background import BackgroundScheduler

    from stockbot.report.daily_report import send_daily_report

    sched = BackgroundScheduler(timezone=KST)

    def guarded(name: str, fn):
        def run(*args):
            now = datetime.now(timezone.utc)
            try:
                fn(*args)
                deps.health.record(f"job:{name}", True, "ok", now)
            except Exception as e:
                log.exception("job %s failed", name)
                deps.health.record(f"job:{name}", False, str(e), now)
                streak = deps.health.status().get(f"job:{name}", {}).get("fail_streak", 0)
                if streak >= 3:
                    deps.notifier.send(f"⚠️ 작업 '{name}'이 {streak}번 연속 실패했습니다: {e}")
        return run

    handlers = {
        "post_close": lambda d: cycle.post_close(d, datetime.now(timezone.utc)),
        "report": lambda d: send_daily_report(deps, d, datetime.now(timezone.utc)),
        "pre_open": lambda d: cycle.pre_open(d, datetime.now(timezone.utc)),
        "open": lambda d, final=False: cycle.at_open(d, datetime.now(timezone.utc), final),
        "open_retry": lambda d, final=False: cycle.at_open(d, datetime.now(timezone.utc), final),
    }

    def plan_today():
        now = datetime.now(KST)
        for j in plan_jobs(now.date(), deps.runtime()):
            if j.run_at > now:
                args = [j.session_date, j.final] if j.name in ("open", "open_retry") else [j.session_date]
                sched.add_job(guarded(j.name, handlers[j.name]), "date", run_date=j.run_at, args=args,
                              id=f"{j.name}:{j.run_at.isoformat()}", replace_existing=True, misfire_grace_time=3600)

    sched.add_job(plan_today, "cron", hour=0, minute=5, id="plan_today", replace_existing=True)
    minutes = deps.runtime().news_poll_minutes
    sched.add_job(guarded("news_poll", lambda: watcher.poll(datetime.now(timezone.utc))), "interval",
                  minutes=minutes, id="news_poll", replace_existing=True, max_instances=1, coalesce=True)
    sched.start()
    plan_today()
    sched.add_job(guarded("catch_up", lambda: catch_up(deps, cycle, datetime.now(timezone.utc))), "date",
                  run_date=datetime.now(KST) + timedelta(seconds=10), id="catch_up", replace_existing=True)
    return sched
