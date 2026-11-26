"""Builds a full Deps graph with in-memory DB and scripted LLMs/prices/news."""
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from engine_helpers import SEAT_IDS, ScriptedRouter, body
from helpers import make_df

from stockbot.broker.base import Quote
from stockbot.broker.paper import PaperBroker
from stockbot.config import RuntimeConfig, Settings
from stockbot.data.news import NewsItem, NewsStore
from stockbot.data.prices import PriceStore
from stockbot.data.verify import NewsVerifier
from stockbot.db import init_db, make_engine, make_session_factory
from stockbot.debate.engine import DebateEngine
from stockbot.debate.seats import DEFAULT_SEATS
from stockbot.execution.approvals import ApprovalQueue
from stockbot.execution.executor import Executor
from stockbot.health import Health
from stockbot.llm.budget import BudgetTracker
from stockbot.market_calendar import KST, trading_session
from stockbot.notify import ListNotifier
from stockbot.pipeline.deps import Deps
from stockbot.risk.rules import OrderIntent
from stockbot.scoring.scoreboard import Scoreboard
from stockbot.sentiment.scorers import KeywordScorer
from stockbot.settings_store import save_runtime

SESSION = date(2024, 6, 3)
NOW = trading_session(SESSION).close_kst + timedelta(minutes=30)          # post-close
OPEN = trading_session(date(2024, 6, 4)).open_kst
MARKET_OPEN_NOW = OPEN + timedelta(hours=1)
TIERS = {"cnbc.com": 1, "marketwatch.com": 1, "smallblog.net": 3}


class Clock:
    def __init__(self, now):
        self.now = now


class MultiFetcher:
    def __init__(self, frames):
        self.frames = frames

    def fetch(self, ticker, start, end):
        df = self.frames.get(ticker)
        if df is None:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return df[(df.index.date >= start) & (df.index.date <= end)]


class QueueSource:
    def __init__(self):
        self.items = []

    def queue(self, *items):
        self.items += items

    def fetch(self, since, tickers):
        out, self.items = self.items, []
        return out


def series(base, last, n=60, vol=600_000, last_vol=None):
    df = make_df([base] * (n - 1) + [last], [vol] * (n - 1) + [last_vol or vol])
    df.index = pd.bdate_range(end=pd.Timestamp(SESSION), periods=n)
    return df


def news(title, domain="cnbc.com", minutes_ago=5, clock=None):
    ts = (clock.now if clock else MARKET_OPEN_NOW) - timedelta(minutes=minutes_ago)
    return NewsItem(url=f"https://{domain}/{abs(hash((title, domain)))}", title=title, source=domain, domain=domain,
                    published_at=ts.astimezone(timezone.utc), tickers=[])


def make_deps(script=None, frames=None, automation="semi", tiers=TIERS):
    engine = make_engine("sqlite://")
    init_db(engine)
    sf = make_session_factory(engine)
    cfg = RuntimeConfig()
    cfg.mode.automation = automation
    with sf() as s:
        save_runtime(s, cfg)
        s.commit()
    frames = frames or {f"UP{k}": series(100, 101, last_vol=600_000 * k) for k in range(3, 10)}
    prices = PriceStore(sf, MultiFetcher(frames))
    clock = Clock(NOW)

    def quote_fn(t):
        last = float(frames[t]["close"].iloc[-1]) if t in frames else 100.0
        return Quote(ticker=t, price=last, ts=clock.now, prev_close=last)

    router = ScriptedRouter(script or {s: [body("BUY", size_pct=0.1)] for s in SEAT_IDS})
    notifier = ListNotifier()
    approvals = ApprovalQueue(sf)
    broker = PaperBroker(sf, quote_fn, initial_cash=cfg.budget_usd)
    settings = Settings(_env_file=None, web_password="pw", pin="1234", secret_key="k", telegram_chat_ids=[111])
    deps = Deps(
        session_factory=sf, settings=settings, prices=prices, news=NewsStore(sf), news_sources=[QueueSource()],
        scorer=KeywordScorer(), verifier=NewsVerifier(sf, tiers), engine=DebateEngine(DEFAULT_SEATS, router, cfg.debate,
                                                                                       now_fn=lambda: clock.now),
        scoreboard=Scoreboard(sf, cfg.debate, SEAT_IDS), broker=broker, executor=Executor(sf, broker, approvals, notifier),
        approvals=approvals, notifier=notifier, health=Health(sf), budget=BudgetTracker(sf, cfg.cost),
        universe=sorted(frames), render_charts=False,
    )
    deps.clock = clock
    deps.frames = frames
    return deps


def hold(deps, ticker, qty=10):
    deps.broker.place(OrderIntent(ticker=ticker, side="buy", qty=qty, kind="new_buy", reason="seed",
                                  idempotency_key=f"seed:{ticker}"), NOW)


def staged_orders(deps):
    from stockbot.models import OrderRow
    with deps.session_factory() as s:
        return s.query(OrderRow).filter(OrderRow.status == "staged").all()
