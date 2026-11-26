"""KST schedule derived from the NYSE calendar (handles DST, holidays, early closes)."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from pydantic import BaseModel

from stockbot.config import RuntimeConfig
from stockbot.market_calendar import KST, is_trading_day, trading_session

log = logging.getLogger(__name__)
JobName = Literal["post_close", "report", "pre_open", "open"]


class ScheduledJob(BaseModel):
    name: JobName
    run_at: datetime
    session_date: date


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
            prev = [j.session_date for j in jobs if j.name == "post_close"]
            last = prev[-1] if prev else kst_day - timedelta(days=1)
            hh, mm = (int(x) for x in cfg.report_time_kst.split(":"))
            jobs.append(ScheduledJob(name="report", run_at=datetime.combine(kst_day, time(hh, mm), KST), session_date=last))
            jobs.append(ScheduledJob(name="pre_open", run_at=s.open_kst - timedelta(minutes=30), session_date=kst_day))
            jobs.append(ScheduledJob(name="open", run_at=s.open_kst, session_date=kst_day))
    return sorted(jobs, key=lambda j: j.run_at)


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
        "open": lambda d: cycle.at_open(d, datetime.now(timezone.utc)),
    }

    def plan_today():
        now = datetime.now(KST)
        for j in plan_jobs(now.date(), deps.runtime()):
            if j.run_at > now:
                sched.add_job(guarded(j.name, handlers[j.name]), "date", run_date=j.run_at, args=[j.session_date],
                              id=f"{j.name}:{j.run_at.isoformat()}", replace_existing=True, misfire_grace_time=3600)

    sched.add_job(plan_today, "cron", hour=0, minute=5, id="plan_today", replace_existing=True)
    minutes = deps.runtime().news_poll_minutes
    sched.add_job(guarded("news_poll", lambda: watcher.poll(datetime.now(timezone.utc))), "interval",
                  minutes=minutes, id="news_poll", replace_existing=True, max_instances=1, coalesce=True)
    sched.start()
    plan_today()
    return sched
