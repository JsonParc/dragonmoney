import json
from datetime import date, datetime, timezone

from llm_fakes import ScriptedClient

from stockbot.config import DebateConfig
from stockbot.debate.engine import DebateContext, DebateEngine
from stockbot.debate.seats import DEFAULT_SEATS, REFEREE_ID
from stockbot.llm.router import LLMRouter

SEAT_IDS = [s.seat_id for s in DEFAULT_SEATS]
CHART = [s.seat_id for s in DEFAULT_SEATS if s.team == "chart"]
NEWS = [s.seat_id for s in DEFAULT_SEATS if s.team == "news"]
SEATS = {s.seat_id: s for s in DEFAULT_SEATS}
W1 = {s: 1.0 for s in SEAT_IDS}
NOW = datetime(2024, 6, 4, 6, 30, tzinfo=timezone.utc)


def body(action, **kw):
    return json.dumps({"action": action, "confidence": 0.7, "rationale": f"because {action}", **kw})


class _FreeBudget:
    def allow(self, c, now): return True
    def record(self, r, now): pass


class ScriptedRouter(LLMRouter):
    def __init__(self, script, referee=None):
        chains = {seat: [ScriptedClient(resps)] for seat, resps in script.items()}
        chains[REFEREE_ID] = [ScriptedClient(referee or ["심판 요약"])]
        super().__init__(chains, _FreeBudget())

    def calls_for(self, seat):
        return len(self.chains[seat][0].calls)


def scripted_router(script, referee=None):
    return ScriptedRouter(script, referee)


def engine(router, cfg=None):
    return DebateEngine(DEFAULT_SEATS, router, cfg or DebateConfig(), now_fn=lambda: NOW)


def ctx(**kw):
    base = dict(ticker="NVDA", sector="Information Technology", as_of=date(2024, 6, 3), kind="regular",
                holding=None, last_price=100.0, chart_signals=["20일선 돌파"], indicator_summary={"rsi14": 60.0},
                chart_png=None, news_digest=["[확인됨·출처 3곳] Nvidia rallies"], macro_digest=["유가 5일 +2%"])
    base.update(kw)
    return DebateContext(**base)
