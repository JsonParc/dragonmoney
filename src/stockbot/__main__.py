"""Entry point: python -m stockbot [--dry-run | --demo]"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "web-ui" / "dist"


def _dry_run() -> int:
    from stockbot.config import Settings
    from stockbot.db import init_db, make_engine, make_session_factory
    from stockbot.health import Health
    from stockbot.market_calendar import KST
    from stockbot.scheduler import plan_jobs
    from stockbot.settings_store import load_runtime

    settings = Settings()
    engine = make_engine(settings.db_url)
    init_db(engine)
    sf = make_session_factory(engine)
    with sf() as s:
        cfg = load_runtime(s)
    today = datetime.now(KST).date()
    for d in (today, today + timedelta(days=1)):
        jobs = plan_jobs(d, cfg)
        print(f"{d} (KST): " + (", ".join(f"{j.name} {j.run_at:%H:%M} [{j.session_date}]" for j in jobs) or "작업 없음"))
    print("health:", Health(sf).status() or "기록 없음")
    print("mode:", cfg.mode.model_dump())
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="stockbot")
    p.add_argument("--dry-run", action="store_true", help="오늘·내일 스케줄과 상태만 출력")
    p.add_argument("--demo", action="store_true", help="가짜 데이터로 관리페이지만 실행 (비밀번호 demo)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if a.dry_run:
        return _dry_run()

    import uvicorn

    from stockbot.web.app import create_app

    if a.demo:
        from stockbot.demo import build_demo

        deps, settings = build_demo()
        uvicorn.run(create_app(deps, settings, static_dir=STATIC), host=a.host, port=a.port)
        return 0

    from stockbot.app_factory import build_deps
    from stockbot.config import Settings
    from stockbot.pipeline.daily import DailyCycle
    from stockbot.pipeline.news_watch import NewsWatcher
    from stockbot.scheduler import start_scheduler
    from stockbot.telegram.bot import KVOffsetStore, TelegramPoller
    from stockbot.telegram.commands import CommandService

    settings = Settings()
    deps = build_deps(settings)
    sched = start_scheduler(deps, DailyCycle(deps), NewsWatcher(deps))
    poller = None
    if settings.telegram_token and settings.telegram_chat_ids:
        poller = TelegramPoller(settings.telegram_token, CommandService(deps, settings),
                                offset_store=KVOffsetStore(deps.session_factory))
        poller.start()
        deps.notifier.send("🤖 주식 봇이 시작됐습니다. /help 로 명령어를 볼 수 있어요.")
    try:
        uvicorn.run(create_app(deps, settings, static_dir=STATIC), host=a.host, port=a.port)
    finally:
        sched.shutdown(wait=False)
        if poller:
            poller.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
