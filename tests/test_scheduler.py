import json
import subprocess
import sys
from datetime import date, datetime, timezone

import httpx

from stockbot.config import RuntimeConfig
from stockbot.data.quotes import finnhub_quote_fn
from stockbot.market_calendar import KST
from stockbot.scheduler import plan_jobs


def test_winter_day_jobs():
    jobs = {j.name: j for j in plan_jobs(date(2026, 12, 2), RuntimeConfig())}
    assert jobs["post_close"].run_at == datetime(2026, 12, 2, 6, 30, tzinfo=KST)
    assert jobs["post_close"].session_date == date(2026, 12, 1)
    assert jobs["report"].run_at == datetime(2026, 12, 2, 17, 30, tzinfo=KST)
    assert jobs["report"].session_date == date(2026, 12, 1)
    assert jobs["pre_open"].run_at == datetime(2026, 12, 2, 23, 0, tzinfo=KST)
    assert jobs["open"].run_at == datetime(2026, 12, 2, 23, 35, tzinfo=KST)  # 5 min after the bell
    assert jobs["open"].session_date == date(2026, 12, 2)


def test_dst_shift():
    jobs = {j.name: j for j in plan_jobs(date(2026, 7, 2), RuntimeConfig())}
    assert jobs["post_close"].run_at == datetime(2026, 7, 2, 5, 30, tzinfo=KST)
    assert jobs["open"].run_at == datetime(2026, 7, 2, 22, 35, tzinfo=KST)


def test_no_jobs_on_holiday():
    jobs = {j.name: j for j in plan_jobs(date(2026, 12, 25), RuntimeConfig())}
    assert "open" not in jobs and "report" not in jobs and "pre_open" not in jobs
    assert jobs["post_close"].run_at == datetime(2026, 12, 25, 3, 30, tzinfo=KST)  # 12/24 early close 13:00 ET


def test_monday_after_weekend():
    names = {j.name for j in plan_jobs(date(2026, 11, 29), RuntimeConfig())}  # Sunday KST
    assert names == set()


def test_finnhub_quote_fn():
    payload = {"c": 101.5, "pc": 100.0, "t": 1764633600}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=json.dumps(payload))))
    q = finnhub_quote_fn("k", client=client)("AAPL")
    assert q.price == 101.5 and q.prev_close == 100.0 and q.ts == datetime.fromtimestamp(1764633600, timezone.utc)


def test_dry_run_exits_zero(tmp_path):
    env = {"STOCKBOT_DB_URL": f"sqlite:///{(tmp_path / 't.db').as_posix()}", "STOCKBOT_WEB_PASSWORD": "pw",
           "STOCKBOT_PIN": "1234", "STOCKBOT_SECRET_KEY": "k", "SYSTEMROOT": "C:\\Windows", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "-m", "stockbot", "--dry-run"], capture_output=True, env=env, cwd=tmp_path,
                       timeout=120)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert "post_close" in r.stdout.decode("utf-8") or "작업 없음" in r.stdout.decode("utf-8")
