from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stockbot.config import RuntimeConfig, Settings
from stockbot.settings_store import load_runtime, save_runtime


@dataclass
class Deps:
    session_factory: Any
    settings: Settings
    prices: Any            # PriceStore
    news: Any              # NewsStore
    news_sources: list
    scorer: Any            # SentimentScorer
    verifier: Any          # NewsVerifier
    engine: Any            # DebateEngine
    scoreboard: Any        # Scoreboard
    broker: Any            # Broker (PaperBroker)
    executor: Any          # Executor
    approvals: Any         # ApprovalQueue
    notifier: Any          # Notifier
    health: Any            # Health
    budget: Any            # BudgetTracker
    universe: list[str] = field(default_factory=list)
    chart_dir: Path = Path("data/charts")
    render_charts: bool = True
    router: Any = None     # LLMRouter (reports / Q&A)
    fundamentals: Any = None  # FundamentalsStore

    def runtime(self) -> RuntimeConfig:
        with self.session_factory() as s:
            return load_runtime(s)

    def save_runtime(self, cfg: RuntimeConfig) -> None:
        with self.session_factory() as s:
            save_runtime(s, cfg)
            s.commit()
