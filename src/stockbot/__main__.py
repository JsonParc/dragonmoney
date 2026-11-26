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


def _state_cli(a) -> int:
    import json
    from datetime import timezone

    from stockbot.state_file import export_state, import_state

    now = datetime.now(timezone.utc)
    if a.export_demo:
        from stockbot.demo import build_demo

        deps, _ = build_demo()
        data = {**export_state(deps, now), "label": "데모 — 가짜 데이터"}
        Path(a.export_demo).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(f"데모 학습 파일 저장: {a.export_demo}")
        return 0
    from stockbot.app_factory import build_deps
    from stockbot.config import Settings

    deps = build_deps(Settings())
    if a.import_file:
        counts = import_state(deps, json.loads(Path(a.import_file).read_text(encoding="utf-8")))
        print("불러옴:", ", ".join(f"{k} {v}건" for k, v in counts.items()))
    if a.export:
        Path(a.export).write_text(json.dumps(export_state(deps, now, include_cache=a.with_cache), ensure_ascii=False),
                                  encoding="utf-8")
        print(f"학습 파일 저장: {a.export}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="stockbot")
    p.add_argument("--dry-run", action="store_true", help="오늘·내일 스케줄과 상태만 출력")
    p.add_argument("--demo", action="store_true", help="가짜 데이터로 관리페이지만 실행 (비밀번호 demo)")
    p.add_argument("--export", metavar="FILE", help="학습 파일 내보내기 (현재 DB → JSON)")
    p.add_argument("--with-cache", action="store_true", help="내보낼 때 LLM 응답 캐시도 포함")
    p.add_argument("--import", dest="import_file", metavar="FILE", help="학습 파일 불러오기 (JSON → 현재 DB)")
    p.add_argument("--export-demo", metavar="FILE", help="가짜 데이터로 만든 학습 파일 (정적 사이트 기본 화면용)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if a.dry_run:
        return _dry_run()
    if a.export or a.import_file or a.export_demo:
        return _state_cli(a)

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
    from stockbot.telegram.bot import KVOffsetStore, TelegramPoller, register_commands
    from stockbot.telegram.commands import CommandService

    settings = Settings()
    deps = build_deps(settings)
    sched = start_scheduler(deps, DailyCycle(deps), NewsWatcher(deps))
    poller = None
    if settings.telegram_token and settings.telegram_chat_ids:
        poller = TelegramPoller(settings.telegram_token, CommandService(deps, settings),
                                offset_store=KVOffsetStore(deps.session_factory))
        poller.start()
        register_commands(settings.telegram_token)
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
