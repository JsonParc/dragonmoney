"""Wire real implementations together."""
from __future__ import annotations

from stockbot.config import RuntimeConfig, Settings
from stockbot.db import init_db, make_engine, make_session_factory
from stockbot.pipeline.deps import Deps


def build_deps(settings: Settings, runtime_cfg: RuntimeConfig | None = None, session_factory=None) -> Deps:
    from stockbot.broker.paper import PaperBroker
    from stockbot.data.news import FinnhubSource, GoogleNewsSource, NewsStore, RssSource, SecEdgarSource, load_feeds
    from stockbot.data.prices import PriceStore, YFinanceFetcher
    from stockbot.data.quotes import finnhub_quote_fn, yfinance_quote_fn
    from stockbot.data.universe import load_universe
    from stockbot.data.verify import NewsVerifier
    from stockbot.debate.engine import DebateEngine
    from stockbot.debate.seats import DEFAULT_SEATS
    from stockbot.execution.approvals import ApprovalQueue
    from stockbot.execution.executor import Executor
    from stockbot.health import Health
    from stockbot.llm.budget import BudgetTracker
    from stockbot.llm.router import build_router
    from stockbot.notify import ConsoleNotifier
    from stockbot.scoring.scoreboard import Scoreboard
    from stockbot.sentiment.scorers import get_scorer
    from stockbot.settings_store import load_runtime
    from stockbot.telegram.bot import TelegramNotifier

    if session_factory is None:
        engine = make_engine(settings.db_url)
        init_db(engine)
        session_factory = make_session_factory(engine)
    if runtime_cfg is None:
        with session_factory() as s:
            runtime_cfg = load_runtime(s)

    router = build_router(settings, runtime_cfg, session_factory)
    sources = [RssSource(load_feeds()), GoogleNewsSource(), SecEdgarSource()]
    if settings.finnhub_key:
        sources.append(FinnhubSource(settings.finnhub_key))
    quote_fn = finnhub_quote_fn(settings.finnhub_key) if settings.finnhub_key else yfinance_quote_fn()
    broker = PaperBroker(session_factory, quote_fn, initial_cash=runtime_cfg.budget_usd)
    approvals = ApprovalQueue(session_factory)
    notifier = (TelegramNotifier(settings.telegram_token, settings.telegram_chat_ids)
                if settings.telegram_token and settings.telegram_chat_ids else ConsoleNotifier())
    seats = [s.seat_id for s in DEFAULT_SEATS]
    return Deps(
        session_factory=session_factory, settings=settings, prices=PriceStore(session_factory, YFinanceFetcher()),
        news=NewsStore(session_factory), news_sources=sources, scorer=get_scorer(),
        verifier=NewsVerifier(session_factory), engine=DebateEngine(DEFAULT_SEATS, router, runtime_cfg.debate),
        scoreboard=Scoreboard(session_factory, runtime_cfg.debate, seats), broker=broker,
        executor=Executor(session_factory, broker, approvals, notifier), approvals=approvals, notifier=notifier,
        health=Health(session_factory), budget=BudgetTracker(session_factory, runtime_cfg.cost),
        universe=[e.ticker for e in load_universe()], chart_dir=settings.data_dir / "charts", router=router,
    )
